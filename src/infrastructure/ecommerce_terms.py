"""电商图片文案常用词库 — 中文短语 → 美国电商风格英文。

翻译时优先整句命中词库；未命中再走 LLM 电商翻译。
词库目标是让常见商品图片短语的翻译符合跨境电商图片语言习惯
（简洁、营销化、贴近卖家表达）。英译统一用美国电商图片标题风格：
Title Case、短促名词短语，少用机械的 "-free" 直译（如用 No Additives 而非 Additive-free）。
"""

ECOMMERCE_TERMS: dict[str, str] = {
    # —— 材质 / 触感 ——
    "柔软细腻": "Soft & Smooth",
    "柔软": "Soft",
    "细腻": "Smooth",
    "舒适亲肤": "Skin-Friendly",
    "亲肤": "Skin-Friendly",
    "温和不刺激": "Gentle & Non-Irritating",
    "不掉絮": "Lint Free",
    "无刺激": "Non-Irritating",
    "零添加": "No Additives",
    "纯植物纤维": "100% Plant Fiber",
    "植物纤维": "Plant Fiber",
    "天然材质": "Natural Material",
    "环保材质": "Eco-Friendly",
    # —— 功能 / 卖点 ——
    "干湿两用": "Dry & Wet Use",
    "干湿双用": "Dry & Wet Use",
    "加厚": "Extra-Thick",
    "加厚升级": "Ultra-Thick Upgrade",
    "加厚洗脸巾": "Ultra-Thick Face Towel",
    "品质升级": "Premium Quality",
    "升级款": "Upgraded",
    "带走残留污垢": "Deep-Cleans Residue",
    "深层清洁": "Deep Cleansing",
    "温和清洁": "Gentle Cleansing",
    "一巾多用": "All-in-One",
    "母婴可用": "Baby Safe",
    "孕妇可用": "Safe for Pregnancy",
    "敏感肌适用": "For Sensitive Skin",
    "旅行便携": "Travel Friendly",
    "便携": "Portable",
    "经久耐用": "Long-Lasting",
    # —— 外观 / 设计 ——
    "3D立体珍珠纹": "3D Pearl Texture",
    "珍珠纹": "Pearl Texture",
    "珍珠纹理": "Pearl-Textured",
    "立体": "3D",
    "3D立体": "3D",
    "表面压花": "Embossed",
    "压花": "Embossed",
    # —— 用法 ——
    "洗脸卸妆": "Wash & Makeup Removal",
    "卸妆": "Makeup Removal",
    "湿敷": "Hydrating Mask",
    # —— 常见包装 ——
    "抽式包装": "Pop-up Box",
    "卷式包装": "Roll Pack",
    "抽取式": "Pop-up",
    "一次性": "Disposable",
    "可重复使用": "Reusable",
}
