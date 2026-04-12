"""
TXT 文本解析器

简单的文本文件读取，支持 UTF-8 和 GBK 编码自动检测。
"""


def extract_text_from_txt(filepath):
    """从TXT提取文本"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        # 尝试其他编码
        try:
            with open(filepath, 'r', encoding='gbk') as f:
                return f.read()
        except Exception as e:
            print(f"      TXT解析错误 {filepath}: {e}")
            return ""
    except Exception as e:
        print(f"      TXT解析错误 {filepath}: {e}")
        return ""
