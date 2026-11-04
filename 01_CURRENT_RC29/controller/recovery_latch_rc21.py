#!/usr/bin/env python3
"""Durable fail-closed session latch. No plant, Modbus, or service APIs.

A marker is persisted before any session start. If the process is interrupted,
next launch refuses until independent physical recovery has been checked.
This protects only cooperating RC21 entry points; NOT independent recovery.
"""
import json
import os
import stat
from pathlib import Path
from datetime import datetime,timezone

class RecoveryRequired(RuntimeError): pass

class RecoveryLatch:
    def __init__(self,path):
        self.path=Path(path)
        if not self.path.is_absolute():raise ValueError('absolute latch path required')
        if self.path.is_symlink() or self.path.parent.is_symlink():raise RecoveryRequired('symlink not permitted')
        if not self.path.parent.is_dir():raise RecoveryRequired('latch directory absent')
    def _syncdir(self):
        fd=os.open(self.path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
    def exists(self):
        if self.path.is_symlink():raise RecoveryRequired('symlink marker')
        return self.path.exists()
    def arm(self,session_id):
        if not isinstance(session_id,str) or not session_id or len(session_id)>128:raise ValueError('invalid session ID')
        # O_EXCL makes launch atomic across cooperating processes.
        try:fd=os.open(self.path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        except FileExistsError as exc:raise RecoveryRequired('existing recovery-required latch') from exc
        try:
            payload=json.dumps({'schema':'SIGEN_RC21_RECOVERY_LATCH','session_id':session_id,'armed_utc':datetime.now(timezone.utc).isoformat(),'state':'RECOVERY_REQUIRED_UNTIL_VERIFIED'},sort_keys=True).encode()+b'\n'
            with os.fdopen(fd,'wb') as f:f.write(payload);f.flush();os.fsync(f.fileno())
            self._syncdir()
        except BaseException:
            # Keep any marker after an uncertain persistence outcome, fail closed.
            raise
    def clear_after_verified_completion(self,session_id,verified):
        if verified is not True:raise RecoveryRequired('verified handback and panel restoration required')
        self._clear_matching(session_id)
    def clear_after_independent_recovery(self,session_id,physical_proof,operator_ack):
        # No public CLI: a separately qualified recovery implementation must supply proof.
        if not callable(physical_proof) or physical_proof() is not True or operator_ack is not True:
            raise RecoveryRequired('independent physical proof and operator approval required')
        self._clear_matching(session_id)
    def _clear_matching(self,session_id):
        fd=os.open(self.path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            st=os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1:raise RecoveryRequired('invalid latch file')
            data=os.read(fd,4096)
            if len(data)==4096:raise RecoveryRequired('oversized latch')
            value=json.loads(data)
            if value.get('schema')!='SIGEN_RC21_RECOVERY_LATCH' or value.get('session_id')!=session_id:
                raise RecoveryRequired('session identity mismatch')
            # Concurrent replacement must not be mistaken for verified old marker.
            current=os.lstat(self.path)
            if (st.st_ino,st.st_dev)!=(current.st_ino,current.st_dev):raise RecoveryRequired('latch changed')
            os.unlink(self.path);self._syncdir()
        finally:os.close(fd)
