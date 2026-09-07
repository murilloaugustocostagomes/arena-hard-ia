import argparse
import json
import os
import re
import time
import concurrent.futures

import shortuuid
import tqdm

from utils.add_markdown_info import count_markdown_elements, remove_pattern
from utils.tokenizer import count_tokens
from utils.config_env import assert_resolved
from utils.completion import (
    load_questions,
    load_model_answers,
    make_config,
    get_endpoint,
    registered_api_completion,
    registered_engine_completion,
    reorg_answer_file,
    filter_questions,
    API_ERROR_OUTPUT,
)


def get_answer(
    question: dict, answer_file: str, settings: dict
):
    # build messages
    messages = []
    if "sys_prompt" in settings:
        messages.append({"role": "system", "content": settings["sys_prompt"]})
        
    messages.append({"role": "user", "content": question["prompt"]})

    # retrieve the api completion function from register
    api_completion_func = registered_api_completion[settings["api_type"]]
    
    # build arguments for api completions
    kwargs = settings | {
        "api_dict": get_endpoint(settings["endpoints"]),
        "messages": messages,
    }
    
    
    output = api_completion_func(**kwargs)
        
    if output is API_ERROR_OUTPUT:
        return
    
    messages.append({"role": "assistant", "content": output})

    # Dump answers
    ans = {
        "uid": question["uid"],
        "ans_id": shortuuid.uuid(),
        "model": model,
        "messages": messages,
        "tstamp": time.time(),
    }
    
    metadata = {"token_len": count_tokens(output["answer"])}
    ans["metadata"] = metadata | count_markdown_elements(
        remove_pattern(
            output['answer'], 
            re.compile("```([^`]*)```")
        ),
        suffix="",
    )

    os.makedirs(os.path.dirname(answer_file), exist_ok=True)
    with open(answer_file, "a", encoding="utf-8") as fout:
        fout.write(json.dumps(ans, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config-file", type=str, default="config/gen_answer_config.yaml"
    )
    parser.add_argument(
        "--endpoint-file", type=str, default="config/api_config.yaml"
    )
    # ADAPTAÇÃO: permite rodadas parciais/baratas antes de gastar com o set inteiro.
    parser.add_argument(
        "--category", "-c", nargs="+", default=None,
        help="Roda só estas categorias (ex.: hard_prompt creative_writing).",
    )
    parser.add_argument(
        "--max-questions", "-n", type=int, default=None,
        help="Limita o número de perguntas (amostra determinística e estratificada).",
    )
    parser.add_argument(
        "--seed", type=int, default=0,
        help="Semente da amostragem. Use a MESMA em gen_answer e gen_judgment.",
    )
    parser.add_argument(
        "--model", "-m", nargs="+", default=None,
        help="Sobrescreve o model_list do arquivo de config.",
    )
    args = parser.parse_args()

    config = make_config(args.config_file)
    endpoints = make_config(args.endpoint_file)

    if args.model:
        config["model_list"] = args.model

    existing_answer = load_model_answers(os.path.join("data", config["bench_name"], "model_answer"))
    
    print(config)

    for model in config["model_list"]:
        assert model in endpoints, (
            f"'{model}' não está em {args.endpoint_file}. "
            f"Adicione uma entrada para ele antes de gerar respostas."
        )
        endpoint_settings = assert_resolved(model, endpoints[model])

        question_file = os.path.join("data", config["bench_name"], "question.jsonl")
        questions = load_questions(question_file)
        questions = filter_questions(
            questions,
            categories=args.category,
            max_questions=args.max_questions,
            seed=args.seed,
        )
        print(f"{len(questions)} perguntas selecionadas para {model}")

        answer_file = os.path.join("data", config["bench_name"], "model_answer", f"{model}.jsonl")
        print(f"Output to {answer_file}")

        if "parallel" in endpoint_settings:
            parallel = endpoint_settings["parallel"]
        else:
            parallel = 1
            
        if 'local_engine' in endpoint_settings and endpoint_settings['local_engine']:
            local_completion_func = registered_engine_completion[endpoint_settings['api_type']]
            
            kwargs = endpoint_settings | {
                "answer_file": answer_file,
                "batch_context": questions,
            }
            local_completion_func(**kwargs)
            
            reorg_answer_file(answer_file)
            
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as executor:
                futures = []
                count = 0
                for index, question in enumerate(questions):
                    if model in existing_answer and question["uid"] in existing_answer[model]:
                        count += 1
                        continue
                    future = executor.submit(
                        get_answer,
                        question,
                        answer_file,
                        endpoint_settings,
                    )
                    futures.append(future)
                if count > 0:
                    print(f"{count} number of existing answers")
                for future in tqdm.tqdm(
                    concurrent.futures.as_completed(futures), total=len(futures)
                ):
                    future.result()

            reorg_answer_file(answer_file)
            