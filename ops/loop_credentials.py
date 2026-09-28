"""Create a host-side credential for the Phase 4 Loop In/Out exercise.

RPC scope audited against Loop v0.35.0-beta and lndclient v0.21.0-2.
Includes payment/signing RPCs required by manual Loop In/Out and recovery.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

# Explicit RPC permissions exclude channel administration, wallet seed export
# and credential administration. DeriveSharedKey is needed to
# unlock Loop's own macaroon database (lndclient/macaroon_service.go).
LOOP_RPC_URIS = (
    '/lnrpc.Lightning/GetInfo',
    '/lnrpc.Lightning/ListChannels',
    '/lnrpc.Lightning/GetNodeInfo',
    '/lnrpc.Lightning/WalletBalance',
    '/lnrpc.Lightning/GetTransactions',
    '/lnrpc.Lightning/EstimateFee',
    '/verrpc.Versioner/GetVersion',
    '/chainrpc.ChainNotifier/RegisterBlockEpochNtfn',
    '/chainrpc.ChainNotifier/RegisterConfirmationsNtfn',
    '/chainrpc.ChainNotifier/RegisterSpendNtfn',
    '/walletrpc.WalletKit/EstimateFee',
    '/walletrpc.WalletKit/ListAccounts',
    '/walletrpc.WalletKit/ListUnspent',
    '/lnrpc.Lightning/AddInvoice',
    '/lnrpc.Lightning/LookupInvoice',
    '/lnrpc.Lightning/DecodePayReq',
    '/lnrpc.Lightning/ListPayments',
    '/lnrpc.Lightning/QueryRoutes',
    '/routerrpc.Router/SendPaymentV2',
    '/routerrpc.Router/TrackPaymentV2',
    '/routerrpc.Router/QueryMissionControl',
    '/routerrpc.Router/XImportMissionControl',
    '/invoicesrpc.Invoices/AddHoldInvoice',
    '/invoicesrpc.Invoices/CancelInvoice',
    '/invoicesrpc.Invoices/SubscribeSingleInvoice',
    '/walletrpc.WalletKit/DeriveNextKey',
    '/walletrpc.WalletKit/DeriveKey',
    '/walletrpc.WalletKit/NextAddr',
    '/walletrpc.WalletKit/SendOutputs',
    '/walletrpc.WalletKit/PublishTransaction',
    '/signrpc.Signer/SignOutputRaw',
    '/signrpc.Signer/MuSig2CreateSession',
    '/signrpc.Signer/MuSig2RegisterNonces',
    '/signrpc.Signer/MuSig2Sign',
    '/signrpc.Signer/MuSig2CombineSig',
    '/signrpc.Signer/MuSig2Cleanup',
    '/signrpc.Signer/DeriveSharedKey',
)


class CredentialError(RuntimeError):
    pass


def create_loop_macaroon(state, env):
    """Bake on the selected testnet node; capture secret output, never log it."""
    command = ['kubectl', '-n', 'lnd-testnet', 'exec', 'lnd-0-0', '-c', 'lnd',
               '--', 'lncli', '--lnddir=/data/.lnd', '--network=testnet']

    def rpc(*args):
        try:
            result = subprocess.run(command + list(args), env=env, text=True,
                                    capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            raise CredentialError('LND 호출 실패: 클러스터 연결과 지갑 unlock 상태를 확인하세요.') from None
        if result.returncode:
            # Neither stdout nor stderr may be echoed: both can contain secrets.
            raise CredentialError('LND 호출 실패: 지갑 unlock·RPC 권한·Pod 상태를 확인하세요.')
        return result.stdout

    try:
        info = json.loads(rpc('getinfo'))
        identity = info.get('identity_pubkey', '')
        if info.get('chains') != [{'chain': 'bitcoin', 'network': 'testnet'}] or not re.fullmatch(r'0[23][0-9a-fA-F]{64}', identity):
            raise CredentialError('선택한 노드의 testnet identity를 확인할 수 없습니다.')
        available = json.loads(rpc('listpermissions'))['method_permissions']
        missing = set(LOOP_RPC_URIS) - set(available)
        if missing:
            raise CredentialError('LND에서 필요한 Loop RPC를 지원하지 않습니다: ' + ', '.join(sorted(missing)))
    except (ValueError, KeyError, TypeError, AttributeError):
        raise CredentialError('LND 노드 또는 권한 응답을 읽을 수 없습니다.') from None

    # Allocate the private destination before minting. Never overwrite a token.
    root = Path(state) / 'credentials'
    directory = path = None
    complete = False
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.is_symlink():
            raise CredentialError('인증 파일 저장 디렉터리는 심볼릭 링크일 수 없습니다.')
        directory = Path(tempfile.mkdtemp(prefix=f'loop-{identity[:12]}-', dir=root))
        path = directory / 'loop.macaroon'
        with path.open('xb') as file:
            os.fchmod(file.fileno(), 0o600)
            encoded = rpc('bakemacaroon', *('uri:' + uri for uri in LOOP_RPC_URIS)).strip()
            if not re.fullmatch(r'[0-9a-fA-F]+', encoded) or len(encoded) % 2:
                raise CredentialError('인증 파일 생성 응답이 올바르지 않습니다. 내용은 출력하지 않습니다.')
            secret = bytes.fromhex(encoded)
            if len(secret) < 32 or secret[0] != 2:
                raise CredentialError('인증 파일 형식을 확인할 수 없습니다.')
            file.write(secret)
            file.flush()
            os.fsync(file.fileno())
        complete = True
        return path
    except (OSError, CredentialError):
        raise CredentialError('Loop 인증 파일을 생성하지 못했습니다. 연결·권한·저장 경로를 확인하세요.') from None
    finally:
        if not complete:
            if path is not None:
                path.unlink(missing_ok=True)
            if directory is not None:
                directory.rmdir()
