"""Read process owner and executable without inspecting arguments or credentials."""
import os
from pathlib import Path


def process_details(pid,reported_name,proc_root=Path('/proc'),lookup_user=None):
    process=proc_root/str(pid)
    result={'name':reported_name or '未知','user':'未知'}
    try:
        uid=process.stat().st_uid
        result['uid']=uid
        if lookup_user is None:
            import pwd
            lookup_user=lambda value:pwd.getpwuid(value).pw_name
        try:result['user']=lookup_user(uid)
        except (KeyError,OSError):result['user']='UID '+str(uid)
    except (OSError,ImportError):pass
    try:
        executable=os.readlink(process/'exe')
        if executable.startswith('/'):result['name']=executable
    except OSError:pass
    return result
