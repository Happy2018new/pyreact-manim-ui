"""Read standard Windows commit/process counters; never access engine memory."""
import ctypes
from ctypes import wintypes

MIN_AVAILABLE_COMMIT=4*1024**3


class PerformanceInformation(ctypes.Structure):
    _fields_=([('cb',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in
        ('CommitTotal','CommitLimit','CommitPeak','PhysicalTotal','PhysicalAvailable','SystemCache','KernelTotal','KernelPaged','KernelNonpaged','PageSize')]+
        [('HandleCount',wintypes.DWORD),('ProcessCount',wintypes.DWORD),('ThreadCount',wintypes.DWORD)])


class ProcessMemoryCounters(ctypes.Structure):
    _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in
        ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
         'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage')]


def snapshot(pid):
    psapi=ctypes.WinDLL('psapi',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    info=PerformanceInformation()
    info.cb=ctypes.sizeof(info)
    psapi.GetPerformanceInfo.argtypes=[ctypes.POINTER(PerformanceInformation),wintypes.DWORD]
    psapi.GetPerformanceInfo.restype=wintypes.BOOL
    if not psapi.GetPerformanceInfo(ctypes.byref(info),info.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    result={'system_commit_total_bytes':int(info.CommitTotal*info.PageSize),'system_commit_limit_bytes':int(info.CommitLimit*info.PageSize),
        'system_commit_available_bytes':int((info.CommitLimit-info.CommitTotal)*info.PageSize),
        'physical_available_bytes':int(info.PhysicalAvailable*info.PageSize),'minimum_available_commit_bytes':MIN_AVAILABLE_COMMIT}
    result['preflight_passed']=result['system_commit_available_bytes']>=MIN_AVAILABLE_COMMIT
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x1000|0x10,False,int(pid))
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        counters=ProcessMemoryCounters()
        counters.cb=ctypes.sizeof(counters)
        psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(ProcessMemoryCounters),wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype=wintypes.BOOL
        if not psapi.GetProcessMemoryInfo(handle,ctypes.byref(counters),counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        result.update(pid=int(pid),process_private_commit_bytes=int(counters.PrivateUsage),
            process_working_set_bytes=int(counters.WorkingSetSize),process_peak_working_set_bytes=int(counters.PeakWorkingSetSize))
    finally:
        kernel.CloseHandle(handle)
    return result
