"""智选志愿 · 江西高考数据采集包（第二试点省）。

入口：`python -m data.jiangxi.run`
模块：config（配置/字段映射） · fetcher（HTTP） · parsers（解析）
      validators（校验/去重） · seeds（种子数据） · collectors（各模块采集器） · run（主程序）
"""
__all__ = ["config", "fetcher", "parsers", "validators", "seeds", "collectors", "run"]
