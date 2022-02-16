#
# Copyright (c) 2021, NVIDIA CORPORATION. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import os
import numpy as np
from cuda import cuda
import tensorrt as trt

def run():
    logger = trt.Logger(trt.Logger.ERROR)
    if os.path.isfile('./engine.trt'):                                          
        with open('./engine.trt', 'rb') as f:                                   
            engine = trt.Runtime(logger).deserialize_cuda_engine( f.read() )    
        if engine == None:                                                  
            print("Failed loading engine!")                                 
            return
        print("Succeeded loading engine!")                                  
    else:                                                                       
        builder                     = trt.Builder(logger)
        network                     = builder.create_network(1<<int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
        profile                     = builder.create_optimization_profile()
        config                      = builder.create_builder_config()
        config.max_workspace_size   = 1<<30

        inputTensor     = network.add_input('inputT0', trt.DataType.FLOAT, [-1,-1,-1])
        profile.set_shape(inputTensor.name, (1,1,1),(3,4,5),(6,8,10))    
        config.add_optimization_profile(profile)

        identityLayer   = network.add_identity(inputTensor)
        network.mark_output(identityLayer.get_output(0))

        engineString    = builder.build_serialized_network(network,config)
        if engineString == None:
            print("Failed building engine!")
            return
        print("Succeeded building engine!")
        with open('./engine.trt', 'wb') as f:
            f.write( engineString )
        engine = trt.Runtime(logger).deserialize_cuda_engine( engineString )

    context     = engine.create_execution_context()
    context.set_binding_shape(0,[3,4,5])
    _, stream   = cuda.cuStreamCreate(0)

    data        = np.arange(3*4*5,dtype=np.float32).reshape(3,4,5)
    inputH0     = np.ascontiguousarray(data.reshape(-1))
    outputH0    = np.empty(context.get_binding_shape(1),dtype = trt.nptype(engine.get_binding_dtype(1)))
    _,inputD0   = cuda.cuMemAllocAsync(inputH0.nbytes,stream)
    _,outputD0  = cuda.cuMemAllocAsync(outputH0.nbytes,stream)

    # 首次捕获 CUDA Graph 并运行
    cuda.cuStreamBeginCapture(stream, cuda.CUstreamCaptureMode.CU_STREAM_CAPTURE_MODE_GLOBAL)    
    cuda.cuMemcpyHtoDAsync(inputD0, inputH0.ctypes.data, inputH0.nbytes, stream)
    context.execute_async_v2([int(inputD0), int(outputD0)], stream)
    cuda.cuMemcpyDtoHAsync(outputH0.ctypes.data, outputD0, outputH0.nbytes, stream)
    #cuda.cuStreamSynchronize(stream)                       # 不用在 graph 内同步
    _,graph = cuda.cuStreamEndCapture(stream)    
    _,graphExe,_ = cuda.cuGraphInstantiate(graph, b"", 0)

    cuda.cuGraphLaunch(graphExe,stream)
    cuda.cuStreamSynchronize(stream)

    print("outputH0Big:", outputH0.shape)
    print(outputH0)
        
    # 输入尺寸改变后，需要重新捕获 CUDA Graph 再运行
    context.set_binding_shape(0,[2,3,4])
    inputH0     = np.ascontiguousarray(-data[:2*3*4].reshape(-1))
    outputH0    = np.empty(context.get_binding_shape(1),dtype = trt.nptype(engine.get_binding_dtype(1)))
    
    cuda.cuStreamBeginCapture(stream, cuda.CUstreamCaptureMode.CU_STREAM_CAPTURE_MODE_GLOBAL)    
    cuda.cuMemcpyHtoDAsync(inputD0, inputH0.ctypes.data, inputH0.nbytes, stream)
    context.execute_async_v2([int(inputD0), int(outputD0)], stream)
    cuda.cuMemcpyDtoHAsync(outputH0.ctypes.data, outputD0, outputH0.nbytes, stream)
    _,graph = cuda.cuStreamEndCapture(stream)    
    _,graphExe,_ = cuda.cuGraphInstantiate(graph, b"", 0)
    
    cuda.cuGraphLaunch(graphExe,stream)
    cuda.cuStreamSynchronize(stream)
    
    print("outputH0Small:", outputH0.shape)
    print(outputH0)

    cuda.cuStreamDestroy(stream)
    cuda.cuMemFree(inputD0)
    cuda.cuMemFree(outputD0)

if __name__ == '__main__':
    os.system("rm -rf ./*.trt")
    cuda.cuInit(0)
    cuda.cuDeviceGet(0)
    run()   # build TensorRT engine and do inference
    run()   # load TensorRT engine and do inference

