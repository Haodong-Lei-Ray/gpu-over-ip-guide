#!/usr/bin/env python3
"""Read Vulkan ordinals and device UUIDs; never assumes nvidia-smi enumeration order."""
import ctypes as c
import json


class App(c.Structure):
    _fields_=[('sType',c.c_uint32),('pNext',c.c_void_p),('pApplicationName',c.c_char_p),('applicationVersion',c.c_uint32),('pEngineName',c.c_char_p),('engineVersion',c.c_uint32),('apiVersion',c.c_uint32)]


class Info(c.Structure):
    _fields_=[('sType',c.c_uint32),('pNext',c.c_void_p),('flags',c.c_uint32),('pApplicationInfo',c.POINTER(App)),('enabledLayerCount',c.c_uint32),('ppEnabledLayerNames',c.c_void_p),('enabledExtensionCount',c.c_uint32),('ppEnabledExtensionNames',c.c_void_p)]


class ID(c.Structure):
    _fields_=[('sType',c.c_uint32),('pNext',c.c_void_p),('deviceUUID',c.c_ubyte*16),('driverUUID',c.c_ubyte*16),('deviceLUID',c.c_ubyte*8),('deviceNodeMask',c.c_uint32),('deviceLUIDValid',c.c_uint32)]


class Props(c.Structure):
    _fields_=[('sType',c.c_uint32),('pNext',c.c_void_p),('props',c.c_ubyte*4096)]


def main():
    vk=c.CDLL('libvulkan.so.1')
    vk.vkCreateInstance.argtypes=[c.POINTER(Info),c.c_void_p,c.POINTER(c.c_void_p)];vk.vkCreateInstance.restype=c.c_int
    vk.vkEnumeratePhysicalDevices.argtypes=[c.c_void_p,c.POINTER(c.c_uint32),c.POINTER(c.c_void_p)];vk.vkEnumeratePhysicalDevices.restype=c.c_int
    vk.vkGetPhysicalDeviceProperties2.argtypes=[c.c_void_p,c.POINTER(Props)]
    vk.vkDestroyInstance.argtypes=[c.c_void_p,c.c_void_p]
    app=App(sType=0,pApplicationName=b'gpu-guide-device-check',apiVersion=(1<<22)|(1<<12))
    info=Info(sType=1,pApplicationInfo=c.pointer(app));instance=c.c_void_p()
    if vk.vkCreateInstance(c.byref(info),None,c.byref(instance))!=0:raise RuntimeError('Cannot initialize Vulkan 1.1')
    try:
        count=c.c_uint32()
        if vk.vkEnumeratePhysicalDevices(instance,c.byref(count),None)!=0:raise RuntimeError('Cannot enumerate Vulkan devices')
        devices=(c.c_void_p*count.value)()
        if vk.vkEnumeratePhysicalDevices(instance,c.byref(count),devices)!=0:raise RuntimeError('Vulkan device list changed')
        result=[]
        for index,device in enumerate(devices):
            ident=ID(sType=1000071004)
            props=Props(sType=1000059001,pNext=c.cast(c.pointer(ident),c.c_void_p))
            vk.vkGetPhysicalDeviceProperties2(device,c.byref(props))
            raw=bytes(props.props)
            result.append({'index':index,'name':raw[20:276].split(b'\0',1)[0].decode(),'uuid_hex':bytes(ident.deviceUUID).hex()})
        print(json.dumps(result))
    finally:vk.vkDestroyInstance(instance,None)


if __name__=='__main__':main()
