import json
import yaml
import argparse
import os
import concurrent.futures

from tqdm import tqdm

from utils.completion import (
    load_questions,
    registered_api_completion,
    load_questions,
    load_model_answers,
    get_endpoint,
    make_config,
    filter_questions,
)

from utils.config_env import assert_resolved
from utils.judge_utils import JUDGE_SETTINGS


def get_score(judgment, patterns):
    import re
    for pattern in patterns:
        pattern = re.compile(pattern)
        
        matches = pattern.findall(judgment.upper())
        matches = [m for m in matches if m != ""]
        
        if len(set(matches)) > 0:
            return matches[-1].strip("\n")
    return None


def pairwise_judgment(question, baseline, answer, reference, configs, settings):
    prompt_args = {
        "QUESTION": question['prompt'],
        "ANSWER_A": baseline["messages"][-1]["content"]['answer'],
        "ANSWER_B": answer["messages"][-1]["content"]['answer'],
    }
    
    if reference:
        prompt_args[f"REFERENCE"] = reference["messages"][-1]["content"]['answer']
        
    user_prompt = configs["prompt_template"].format(**prompt_args)
    messages = [
        {
            "role": "system", 
            "content": JUDGE_SETTINGS[question["category"]]["system_prompt"],
        },
        {
            "role": "user", 
            "content": user_prompt,
        }
    ]

    # build arguments for api completions
    kwargs = settings | {
        "api_dict": get_endpoint(settings["endpoints"]),
        "messages": messages,
    }
    kwargs['temperature'] = configs['temperature']
    kwargs['max_tokens'] = configs['max_tokens']
    
    api_completion_func = registered_api_completion[settings["api_type"]]
    output = api_completion_func(**kwargs)
    
    if output is None:
        return None

    score = get_score(output['answer'], configs["regex_patterns"])

    result = {
        "score": score,
        "judgment": output,
        "prompt": messages,
    }
    return result


def judgment(args):
    answer = args['answer']
    baseline = args['baseline']
    
    output = {
        "uid": args['question']["uid"],
        "category": args['question']["category"],
        "judge": args['configs']['judge_model'],
        "model": answer["model"],
        "baseline": baseline["model"],
        "games": []
    }

    # round 1
    result = pairwise_judgment(
        question=args['question'],
        baseline=baseline,
        answer=answer,
        reference=args['reference'],
        configs=args['configs'],
        settings=args['settings'],
    )
    output["games"].append(result)
        
    # round 2
    result = pairwise_judgment(
        question=args['question'],
        baseline=answer,
        answer=baseline,
        reference=args['reference'],
        configs=args['configs'],
        settings=args['settings'],
    )
    output["games"].append(result)

    with open(args['output_file'], "a", encoding="utf-8") as f:
        f.write(json.dumps(output, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--setting-file", type=str, default="config/arena-hard-v2.0.yaml")
    parser.add_argument("--endpoint-file", type=str, default="config/api_config.yaml")
    # ADAPTAÇÃO: mesmo recorte de perguntas usado em gen_answer.py.
    parser.add_argument(
        "--category", "-c", nargs="+", default=None,
        help="Julga só estas categorias (ex.: hard_prompt creative_writing).",
    )
    parser.add_argument(
        "--max-questions", "-n", type=int, default=None,
        help="Limita o número de perguntas (amostra determinística e estratificada).",
    )
    parser.add_argument(
        "--seed", type=int, default=0,
        help="Semente da amostragem. Use a MESMA usada em gen_answer.py.",
    )
    parser.add_argument(
        "--model", "-m", nargs="+", default=None,
        help="Sobrescreve o model_list do arquivo de config.",
    )
    args = parser.parse_args()
    print(args)

    configs = make_config(args.setting_file)
    endpoint_list = make_config(args.endpoint_file)

    if args.model:
        configs["model_list"] = args.model

    print(f'judge model: {configs["judge_model"]}, reference: {configs["reference"]}, temperature: {configs["temperature"]}, max tokens: {configs["max_tokens"]}')

    question_file = os.path.join("data", configs["bench_name"], "question.jsonl")
    answer_dir = os.path.join("data", configs["bench_name"], "model_answer")

    questions = load_questions(question_file)
    questions = filter_questions(
        questions,
        categories=args.category,
        max_questions=args.max_questions,
        seed=args.seed,
    )
    print(f"{len(questions)} perguntas selecionadas para julgamento")

    model_answers = load_model_answers(answer_dir)
    
    # if user choose a set of models, only judge those models
    models = [model for model in configs["model_list"]]
        
    if configs["reference"]:
        assert not configs["reference"] in models, "ERROR: one of the models being evaluated is used as reference."
        ref_answers = [answer_dir[model] for model in configs["reference"]]
    else:
        ref_answers = None
    
    output_files = {}
    output_dir = f"data/{configs['bench_name']}/model_judgment/{configs['judge_model']}"
    for model in models:
        output_files[model] = os.path.join(
            output_dir,
            f"{model}.jsonl",
        )

    for output_file in output_files.values():
        os.makedirs(os.path.dirname(output_file), exist_ok=True)

    existing_judgments = load_model_answers(output_dir)

    assert configs["judge_model"] in endpoint_list, (
        f"O juiz '{configs['judge_model']}' não está em {args.endpoint_file}."
    )
    endpoint_settings = assert_resolved(configs["judge_model"], endpoint_list[configs["judge_model"]])

    with concurrent.futures.ThreadPoolExecutor(max_workers=endpoint_settings["parallel"]) as executor:
        futures = []
        for model in models:
            count = 0
            for question in questions:
                uid = question["uid"]

                kwargs = {}
                kwargs["question"] = question
                # ADAPTAÇÃO: o upstream só checava `model in model_answers and
                # uid not in ...`, então um modelo sem NENHUMA resposta estourava
                # um KeyError críptico. Agora a mensagem diz o que fazer.
                if model not in model_answers:
                    raise SystemExit(
                        f"Não há respostas para '{model}' em {answer_dir}. "
                        f"Rode `python gen_answer.py` para esse modelo primeiro."
                    )
                if uid not in model_answers[model]:
                    print(f"Warning: {model} answer to {question['uid']} cannot be found.")
                    continue

                if model in existing_judgments and uid in existing_judgments[model]:
                    count += 1
                    continue

                baseline_model = JUDGE_SETTINGS[question["category"]]["baseline"]
                if baseline_model not in model_answers:
                    raise SystemExit(
                        f"Falta o baseline '{baseline_model}' (categoria "
                        f"'{question['category']}') em {answer_dir}.\n"
                        f"Baixe as respostas oficiais com `python scripts/fetch_data.py` "
                        f"ou gere-as com `python gen_answer.py -m {baseline_model}`."
                    )
                if uid not in model_answers[baseline_model]:
                    print(f"Warning: baseline {baseline_model} answer to {uid} cannot be found.")
                    continue

                kwargs["answer"] = model_answers[model][uid]
                kwargs["baseline"] = model_answers[baseline_model][uid]
                
                if ref_answers:
                    kwargs["reference"] = [ref_answer[uid] for ref_answer in ref_answers]
                else:
                    kwargs["reference"] = None
                    
                kwargs["configs"] = configs
                kwargs["settings"] = endpoint_settings
                kwargs["output_file"] = output_files[model]
                                
                future = executor.submit(judgment, kwargs)
                futures.append(future)

            if count > 0:
                print(f"{count} number of existing judgments")

        for future in tqdm(
            concurrent.futures.as_completed(futures), total=len(futures)
        ):
            future.result()
