"""
截图技能脚本包
"""
from .screenshot import (
    screenshot_full,
    screenshot_region,
    screenshot_base64,
    get_monitors,
    main
)

__all__ = [
    'screenshot_full',
    'screenshot_region', 
    'screenshot_base64',
    'get_monitors',
    'main'
]
