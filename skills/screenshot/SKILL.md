---
name: screenshot
description: Windows屏幕截图技能。当用户需要截取屏幕、获取屏幕快照、保存截图时自动触发。支持全屏、指定区域截图，可保存为文件或返回Base64。
---

# Windows 屏幕截图技能

## 功能概述

提供 Windows 系统屏幕截图功能，支持全屏截图、指定区域截图，可保存为文件或返回 Base64 格式。

## 实现方式

### 方式一：Python（推荐，使用 mss 库）

```python
import mss
import base64
from datetime import datetime

def screenshot_full(save_path: str = None, return_base64: bool = False):
    """
    全屏截图
    
    Args:
        save_path: 保存路径，为None时自动生成
        return_base64: 是否返回Base64编码
    
    Returns:
        文件路径 或 Base64字符串
    """
    with mss.mss() as sct:
        # 截取所有屏幕
        monitor = sct.monitors[0]  # 0 = 所有屏幕，1 = 主屏幕
        screenshot = sct.shot(monitor=monitor, output=None)
        
        # 生成文件名
        if save_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = f"screenshot_{timestamp}.png"
        
        # 保存文件
        sct.shot(output=save_path)
        
        if return_base64:
            with open(save_path, "rb") as f:
                return base64.b64encode(f.read()).decode()
        
        return save_path


def screenshot_region(left: int, top: int, width: int, height: int, save_path: str = None):
    """
    区域截图
    
    Args:
        left: 左上角 X 坐标
        top: 左上角 Y 坐标
        width: 宽度
        height: 高度
        save_path: 保存路径
    
    Returns:
        保存的文件路径
    """
    with mss.mss() as sct:
        monitor = {
            "left": left,
            "top": top,
            "width": width,
            "height": height
        }
        
        if save_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = f"screenshot_region_{timestamp}.png"
        
        sct.shot(monitor=monitor, output=save_path)
        return save_path
```

### 方式二：Python（使用 PIL + pyautogui）

```python
from PIL import ImageGrab
import datetime

def screenshot_pil(save_path: str = None):
    """使用 PIL 截图"""
    if save_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = f"screenshot_{timestamp}.png"
    
    screenshot = ImageGrab.grab()
    screenshot.save(save_path)
    return save_path


def screenshot_region_pil(left: int, top: int, right: int, bottom: int, save_path: str = None):
    """区域截图 - PIL 方式"""
    if save_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = f"screenshot_region_{timestamp}.png"
    
    screenshot = ImageGrab.grab(bbox=(left, top, right, bottom))
    screenshot.save(save_path)
    return save_path
```

### 方式三：PowerShell 命令

```powershell
# 使用 .NET 类截图
Add-Type -AssemblyName System.Windows.Forms

$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object System.Drawing.Bitmap($screen.Width, $screen.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$savePath = ".\screenshot_$timestamp.png"

$bitmap.Save($savePath)
$graphics.Dispose()
$bitmap.Dispose()

Write-Output "截图已保存: $savePath"
```

## 依赖安装

```bash
# mss 方式（推荐，更快）
pip install mss

# PIL 方式
pip install Pillow
```

## 使用示例

### 完整流程示例

```python
# 1. 全屏截图并保存
save_path = screenshot_full()
print(f"截图已保存: {save_path}")

# 2. 保存到指定位置
save_path = screenshot_full("D:/Screenshots/my_screenshot.png")

# 3. 获取 Base64 编码（用于API返回）
base64_data = screenshot_full(return_base64=True)

# 4. 区域截图（左上角100,100，宽高300x200）
region_path = screenshot_region(100, 100, 300, 200, "D:/region.png")
```

## 触发场景

- 用户说"截图"、"截屏"、"屏幕快照"
- 用户说"保存当前屏幕"
- 用户需要获取屏幕内容用于分析或传输

## 注意事项

1. **权限**：确保有写入目标目录的权限
2. **路径**：Windows 路径使用反斜杠或正斜杠均可
3. **格式**：默认保存为 PNG 格式，保持高质量
4. **多屏幕**：使用 `sct.monitors[0]` 可截取所有屏幕组合
5. **性能**：mss 库比 PIL 更快，推荐优先使用
