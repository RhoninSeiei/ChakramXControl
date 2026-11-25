"""Windows HID transport for the ROG Chakram X configuration interface."""

import time
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from uuid import UUID

import hid


PRODUCTS = {0x1A18: "USB 有线", 0x1A1A: "2.4 GHz 接收器"}


@dataclass(frozen=True)
class Device:
    path: bytes
    pid: int

    @property
    def label(self):
        return PRODUCTS[self.pid]


class PropertyKey(ctypes.Structure):
    _fields_ = [("guid", ctypes.c_ubyte * 16), ("pid", wintypes.DWORD)]

    def __init__(self, guid, key):
        super().__init__((ctypes.c_ubyte * 16).from_buffer_copy(UUID(guid).bytes_le), key)


def container_id(path):
    """Get Windows' physical-device container GUID for a HID interface path."""
    cfg = ctypes.WinDLL("cfgmgr32")
    instance_key = PropertyKey("78c34fc8-104a-4aca-9ea4-524d52996e57", 256)
    container_key = PropertyKey("8c7ed206-3f8a-4827-b3ab-ae9e1faefc6c", 2)
    name = ctypes.create_unicode_buffer(512)
    size = wintypes.DWORD(ctypes.sizeof(name))
    kind = wintypes.DWORD()
    node = wintypes.DWORD()
    if cfg.CM_Get_Device_Interface_PropertyW(path.decode(), ctypes.byref(instance_key),
            ctypes.byref(kind), ctypes.byref(name), ctypes.byref(size), 0):
        raise OSError("无法识别鼠标的 Windows 设备实例。")
    if cfg.CM_Locate_DevNodeW(ctypes.byref(node), name, 0):
        raise OSError("鼠标设备实例已断开。")
    data = (ctypes.c_ubyte * 16)()
    size.value = ctypes.sizeof(data)
    if cfg.CM_Get_DevNode_PropertyW(node, ctypes.byref(container_key), ctypes.byref(kind),
            ctypes.byref(data), ctypes.byref(size), 0) or size.value != 16:
        raise OSError("无法识别鼠标的物理设备。")
    return str(UUID(bytes_le=bytes(data)))


def gamepad_present(device):
    candidates = [info for info in hid.enumerate(0x0B05, device.pid)
                  if info["usage_page"] == 1 and info["usage"] in (4, 5)]
    if not candidates:
        return False
    target = container_id(device.path)
    return any(container_id(info["path"]) == target for info in candidates)


def devices():
    return [
        Device(info["path"], pid)
        for pid in PRODUCTS
        for info in hid.enumerate(0x0B05, pid)
        if info["interface_number"] == 0 and info["usage_page"] >= 0xFF00
        and info["usage"] == 1
    ]


@contextmanager
def configuration_session(device):
    # Serialize complete read/modify/verify operations across our app instances.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    mutex = kernel.CreateMutexW(None, False, "Local\\ChakramXConfigurationSession")
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    dev = None
    try:
        if ctypes.get_last_error() == 183:
            raise RuntimeError("另一个配置操作正在进行，请稍后刷新。")
        dev = hid.device()
        dev.open_path(device.path)
        yield Transport(dev)
    finally:
        try:
            if dev is not None:
                dev.close()
        finally:
            kernel.CloseHandle(mutex)


class Transport:
    def __init__(self, handle):
        self.handle = handle

    def _send(self, request):
        if not 2 <= len(request) <= 64:
            raise ValueError("无效的 HID 命令长度。")
        for _ in range(32):
            if not self.handle.read(64, 1):
                break
        packet = b"\x00" + request.ljust(64, b"\x00")
        if self.handle.write(packet) != len(packet):
            raise OSError("鼠标未接收完整的配置请求。")

    def set_gamepad_flag(self, enabled):
        # P708 HAL's SetJoystickMode sends this once. USB can reset before an ACK.
        if type(enabled) is not bool:
            raise ValueError("游戏控制器开关值无效。")
        self._send(bytes((0x51, 0x40, 0, 0, int(enabled))))

    def exchange(self, request):
        self._send(request)
        deadline = time.monotonic() + 1.25
        while (remaining := deadline - time.monotonic()) > 0:
            response = bytes(self.handle.read(64, max(1, int(remaining * 1000))))
            if response[:2] == b"\xff\xaa":
                raise OSError(f"鼠标固件拒绝了命令 {request[:3].hex(' ')}。")
            # The P708 lighting reply reports selector zero even for wheel/front.
            match_selector = request[0] == 0x12 and request[:2] != b"\x12\x03"
            prefix = request[:3].ljust(3, b"\x00") if match_selector else request[:2]
            if len(response) == 64 and response.startswith(prefix):
                return response
        raise TimeoutError(f"等待鼠标应答超时（{request[:3].hex(' ')}）。请确认连接并刷新。")


def gamepad_flag(tr):
    value = tr.exchange(b"\x12\x00\x06")[4]
    if value not in (0, 1):
        raise RuntimeError(f"固件返回了未知的控制器开关值 {value}。")
    return bool(value)


def wait_gamepad(device, enabled, timeout=8):
    """Reopen the control interface after the device changes USB descriptors."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.2)
        try:
            with configuration_session(device) as tr:
                if gamepad_flag(tr) == enabled and gamepad_present(device) == enabled:
                    return
        except (OSError, RuntimeError):
            continue
    raise RuntimeError("鼠标正在重新连接，尚未确认 Windows 游戏控制器状态，请稍后刷新。")
