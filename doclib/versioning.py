# -*- coding: utf-8 -*-
"""解析管线版本。

**规则：只要改动了「解析」或「切块」逻辑，就把 PARSE_VERSION +1。**

每个文档在入库时记录当时的 PARSE_VERSION；只要它和当前值不一致，
`importer.rebuild()` 就会自动重新解析、重新切块、重建全文索引。

这样将来修好 PDF 解析、OCR 变准、切块策略调整时，
不需要手动删除重导，也不会让 AI 用着过期的旧索引。
"""

# v1: 初始版本（docx / pptx / md / txt / pdf / 图片 / doc）
# v2: 加入 PDF 扫描件 OCR 与章节标题参与检索
PARSE_VERSION = 3

# 切块参数变化也算解析版本；这里留一个显式提醒
NOTE = "改动 doclib/readers.py、chunker.py、doclib_reader.py 或切块参数后，请把 PARSE_VERSION +1"
