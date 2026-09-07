import pandas as pd
import re
import os
import argparse

from tqdm import tqdm

try:
    from utils.tokenizer import count_tokens
except ModuleNotFoundError:  # executado diretamente: `python utils/add_markdown_info.py`
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.tokenizer import count_tokens
from glob import glob


def count_markdown_elements(markdown_text, suffix):
    counters = {
        f"header_count{suffix}": {
            "h1": len(re.findall(r"^#{1}\s", markdown_text, re.MULTILINE)),
            "h2": len(re.findall(r"^#{2}\s", markdown_text, re.MULTILINE)),
            "h3": len(re.findall(r"^#{3}\s", markdown_text, re.MULTILINE)),
            "h4": len(re.findall(r"^#{4}\s", markdown_text, re.MULTILINE)),
            "h5": len(re.findall(r"^#{5}\s", markdown_text, re.MULTILINE)),
            "h6": len(re.findall(r"^#{6}\s", markdown_text, re.MULTILINE)),
        },
        f"list_count{suffix}": {
            "ordered": len(re.findall(r"^\s*\d+\.\s", markdown_text, re.MULTILINE)),
            "unordered": len(re.findall(r"^\s*[-*+]\s", markdown_text, re.MULTILINE)),
        },
        f"bold_count{suffix}": {
            "**": len(re.findall(r"\*\*[^*\n]+\*\*", markdown_text)),
            "__": len(re.findall(r"__[^_\n]+__", markdown_text)),
        },
    }
    return counters


def remove_pattern(answer, pattern):
    blocks = pattern.findall(answer)
    for block in blocks:
        answer = answer.replace(block, "")
    return answer


def get_element_counts(df, column):
    pattern = re.compile("```([^`]*)```")
    answers = df[column].map(
        lambda messages: messages[-1]["content"]["answer"]
    )
    results = answers.map(
        lambda answer: count_markdown_elements(
            remove_pattern(answer, pattern),
            suffix="",  # Remove code block first
        )
    )

    return results.tolist()


def add_markdown_meta(row, encoder=None):
    # ADAPTAÇÃO: usa utils.tokenizer.count_tokens, que não quebra sem rede.
    conv_meta = {"token_len": count_tokens(row["messages"][-1]["content"]["answer"])}
    return conv_meta | row["markdown_meta"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=str, required=True)
    parser.add_argument("--output-dir", type=str, required=True)
    args = parser.parse_args()
    
    print("loading file...")
    for file in tqdm(glob(f"{args.dir}/*.jsonl")):
        data = pd.read_json(file, lines=True)

        temp = data[["uid", "messages"]].copy()
        temp["markdown_meta"] = get_element_counts(data, column="messages")

        data["metadata"] = temp.apply(add_markdown_meta, axis=1)
        
        output_file = file.replace(args.dir, args.output_dir)
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        data.to_json(output_file, orient="records", lines=True)
        