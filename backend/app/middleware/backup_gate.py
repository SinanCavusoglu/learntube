"""Drain requests before snapshots or restores and reject nonlocal backup access."""

import asyncio
from ipaddress import ip_address
from urllib.parse import urlsplit

from app.services.backups import MAX_ARCHIVE_BYTES


class BackupGate:
    def __init__(self, app):
        self.app = app
        self.condition = asyncio.Condition()
        self.active = 0
        self.exclusive = False
        self.waiting_exclusive = 0

    @staticmethod
    def _local(scope) -> bool:
        headers = {name.decode('latin1').lower(): value.decode('latin1') for name, value in scope.get('headers', [])}
        if any(headers.get(name) for name in ('x-forwarded-for', 'x-real-ip', 'forwarded', 'tailscale-user-login')):
            return False
        client = scope.get('client')
        host = client[0] if client else ''
        if host != 'testclient':
            try:
                if not ip_address(host).is_loopback:
                    return False
            except ValueError:
                return False
        authority = headers.get('host', '').split(':')[0].strip('[]').lower()
        if authority not in {'localhost', '127.0.0.1', '::1', 'testserver'}:
            return False
        origin = headers.get('origin')
        return not origin or (origin in {'http://localhost:5173', 'http://127.0.0.1:5173',
                                        'http://localhost:8001', 'http://127.0.0.1:8001'}
                              and urlsplit(origin).hostname in {'localhost', '127.0.0.1'})

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        backup = scope.get('path', '').startswith('/api/backups/')
        if backup and not self._local(scope):
            body = b'{"detail":"Backup and restore are available only on this computer."}'
            await send({'type': 'http.response.start', 'status': 403,
                        'headers': [(b'content-type', b'application/json'), (b'content-length', str(len(body)).encode())]})
            await send({'type': 'http.response.body', 'body': body})
            return
        if backup and scope.get('path') in {'/api/backups/inspect', '/api/backups/restore'}:
            headers = {name.decode('latin1').lower(): value.decode('latin1') for name, value in scope.get('headers', [])}
            try:
                too_large = int(headers.get('content-length', '0')) > MAX_ARCHIVE_BYTES + 1024 * 1024
            except ValueError:
                too_large = True
            if too_large:
                body = b'{"detail":"The backup upload exceeds the size limit."}'
                await send({'type': 'http.response.start', 'status': 413,
                            'headers': [(b'content-type', b'application/json'), (b'content-length', str(len(body)).encode())]})
                await send({'type': 'http.response.body', 'body': body})
                return
        async with self.condition:
            if backup:
                self.waiting_exclusive += 1
                try:
                    await self.condition.wait_for(lambda: not self.exclusive and self.active == 0)
                    self.exclusive = True
                finally:
                    self.waiting_exclusive -= 1
            else:
                await self.condition.wait_for(lambda: not self.exclusive and self.waiting_exclusive == 0)
                self.active += 1
        try:
            await self.app(scope, receive, send)
        finally:
            async with self.condition:
                if backup:
                    self.exclusive = False
                else:
                    self.active -= 1
                self.condition.notify_all()
