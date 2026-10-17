# 设备注册 API URL
REGISTER_URL = "https://log.snssdk.com/service/2/device_register/"

# Settings API URL (获取 Token)
SETTINGS_URL = "https://is.snssdk.com/service/settings/v3/"

# ASR WebSocket URL
WEBSOCKET_URL = "wss://frontier-audio-ime-ws.doubao.com/ocean/api/v1/ws"

# 豆包输入法的 APP ID
AID = 401734

# 应用配置 (豆包输入法)
APP_CONFIG = {
    "aid": AID,
    "app_name": "oime",
    "version_code": 100102018,
    "version_name": "1.1.2",
    "manifest_version_code": 100102018,
    "update_version_code": 100102018,
    "channel": "official",
    "package": "com.bytedance.android.doubaoime",
}

# 默认设备配置 (模拟 Pixel 7 Pro)
DEFAULT_DEVICE_CONFIG = {
    "device_platform": "android",
    "os": "android",
    "os_api": "34",
    "os_version": "16",
    "device_type": "Pixel 7 Pro",
    "device_brand": "google",
    "device_model": "Pixel 7 Pro",
    "resolution": "1080*2400",
    "dpi": "420",
    "language": "zh",
    "timezone": 8,
    "access": "wifi",
    "rom": "UP1A.231005.007",
    "rom_version": "UP1A.231005.007",
}

USER_AGENT = "com.bytedance.android.doubaoime/100102018 (Linux; U; Android 16; en_US; Pixel 7 Pro; Build/BP2A.250605.031.A2; Cronet/TTNetVersion:94cf429a 2025-11-17 QuicVersion:1f89f732 2025-05-08)"