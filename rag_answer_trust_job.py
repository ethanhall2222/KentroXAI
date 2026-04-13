# Databricks notebook source
import os
import sys

REPO_ROOT = "/Workspace/Users/ethan.hall@kentro.us/ts-rnd-explainable-ai"
REPO_SRC = f"{REPO_ROOT}/src"

if REPO_SRC not in sys.path:
    sys.path.insert(0, REPO_SRC)

os.environ["OPENAI_API_KEY"] = dbutils.secrets.get("dbss-wvu-poc", "openai-key")



# COMMAND ----------

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pyspark.sql.functions import col, lower, when
from pyspark.sql.types import (
    ArrayType,
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

from trusted_ai_toolkit.cli import _compose_model_prompt
from trusted_ai_toolkit.config import load_config
from trusted_ai_toolkit.databricks_pipeline import (
    build_governance_run_row,
    run_databricks_answer_pipeline,
)
from trusted_ai_toolkit.model_client import invoke_model


# COMMAND ----------

CONFIG_PATH = f"{REPO_ROOT}/config.yaml"

CATALOG = "wvu"
SCHEMA = "ethanhall"
SILVER_TABLE = f"{CATALOG}.{SCHEMA}.silver_chunks"
GOVERNANCE_TABLE = f"{CATALOG}.{SCHEMA}.kentroxai_governance_runs"

GENERATION_MODEL = "gpt-4.1-mini"
TOP_K = 5

base_cfg = load_config(Path(CONFIG_PATH))
cfg = base_cfg.model_copy(
    update={
        "adapters": base_cfg.adapters.model_copy(
            update={
                "provider": "openai_compatible",
                "endpoint": "https://api.openai.com/v1",
                "model": GENERATION_MODEL,
                "api_key_env": "OPENAI_API_KEY",
                "request_format": "responses",
            }
        )
    }
)


# COMMAND ----------

def retrieve_chunks(question: str, top_k: int = TOP_K) -> list[dict]:
    terms = [term.lower() for term in re.findall(r"[A-Za-z0-9]+", question) if len(term) > 2][:8]

    df = spark.table(SILVER_TABLE)

    if not terms:
        rows = df.limit(top_k).collect()
    else:
        score_expr = None
        for term in terms:
            term_score = when(lower(col("chunk_text")).contains(term), 1).otherwise(0)
            score_expr = term_score if score_expr is None else score_expr + term_score

        ranked = (
            df.withColumn("retrieval_score_raw", score_expr)
              .filter(col("retrieval_score_raw") > 0)
              .orderBy(col("retrieval_score_raw").desc())
              .limit(top_k)
        )
        rows = ranked.collect()

    chunks = []
    for rank, row in enumerate(rows, start=1):
        chunk = row.asDict()
        chunk_id = chunk.get("chunk_id") or chunk.get("id") or f"chunk-{rank}"
        doc_uri = chunk.get("doc_uri") or chunk.get("uri") or chunk.get("source_uri") or ""
        chunk_text = chunk.get("chunk_text") or chunk.get("text") or chunk.get("snippet") or chunk.get("content") or ""
        chunks.append(
            {
                **chunk,
                "chunk_id": str(chunk_id),
                "doc_uri": str(doc_uri),
                "chunk_text": str(chunk_text),
                "retrieval_score": float(chunk.get("retrieval_score_raw", top_k - rank + 1)),
                "rank": rank,
            }
        )

    return chunks


# COMMAND ----------

def generate_answer_with_openai(question: str, retrieved_chunks: list[dict]) -> str:
    retrieved_contexts = [
        {
            "id": chunk["chunk_id"],
            "uri": chunk["doc_uri"],
            "text": chunk["chunk_text"],
            "score": chunk.get("retrieval_score"),
            "rank": chunk.get("rank"),
        }
        for chunk in retrieved_chunks
    ]

    prompt = _compose_model_prompt(question, retrieved_contexts)
    prompt = (
        "Answer only from the provided sources. "
        "If the sources are insufficient, say that clearly. "
        "Do not add unsupported claims.\n\n"
        f"{prompt}"
    )

    invocation = invoke_model(prompt, cfg)
    return invocation.output_text.strip()


# COMMAND ----------

governance_schema = StructType([
    StructField("run_id", StringType(), True),
    StructField("request_id", StringType(), True),
    StructField("created_at", TimestampType(), True),
    StructField("query_text", StringType(), True),
    StructField("retrieved_chunk_count", IntegerType(), True),
    StructField("top_doc_uris", ArrayType(StringType()), True),
    StructField("overall_status", StringType(), True),
    StructField("go_no_go", StringType(), True),
    StructField("answer_verdict", StringType(), True),
    StructField("answer_trust_score", DoubleType(), True),
    StructField("governance_score", DoubleType(), True),
    StructField("trust_score", DoubleType(), True),
    StructField("evidence_completeness", DoubleType(), True),
    StructField("artifact_dir", StringType(), True),
    StructField("scorecard_json_path", StringType(), True),
    StructField("answer_text", StringType(), True),
    StructField("retrieved_chunks_json", StringType(), True),
])


# COMMAND ----------

def run_job(question: str, request_id: str) -> dict:
    retrieved_chunks = retrieve_chunks(question, top_k=TOP_K)

    if not retrieved_chunks:
        raise ValueError("No retrieved chunks found for the question.")

    answer = generate_answer_with_openai(question, retrieved_chunks)

    result = run_databricks_answer_pipeline(
        config_path=CONFIG_PATH,
        question=question,
        answer=answer,
        retrieved_chunks=retrieved_chunks,
        system_context={
            "model_provider": "openai",
            "model_name": GENERATION_MODEL,
            "embedding_model": "databricks-rag-embedding",
            "endpoint_name": "databricks-notebook-job",
        },
        provider="openai_compatible",
        endpoint="https://api.openai.com/v1",
        model=GENERATION_MODEL,
        api_key_env="OPENAI_API_KEY",
        request_format="responses",
    )

    scorecard_payload = result["scorecard"]

    row = build_governance_run_row(
        run_id=scorecard_payload["run_id"],
        question=question,
        answer=answer,
        retrieved_chunks=retrieved_chunks,
        artifact_dir=result["run_dir"],
        scorecard_json_path=result["scorecard_json_path"],
        scorecard_payload=scorecard_payload,
    )

    row["request_id"] = request_id
    row["created_at"] = datetime.now(timezone.utc)

    df = spark.createDataFrame([row], schema=governance_schema)
    df.write.mode("append").saveAsTable(GOVERNANCE_TABLE)

    return {
        "request_id": request_id,
        "question": question,
        "answer": answer,
        "retrieved_chunks": retrieved_chunks,
        "scorecard": scorecard_payload,
        "run_dir": result["run_dir"],
        "scorecard_json_path": result["scorecard_json_path"],
    }


# COMMAND ----------

import json
from pathlib import Path

dbutils.widgets.text("question", "")
dbutils.widgets.text("request_id", "")

question = dbutils.widgets.get("question").strip()
request_id = dbutils.widgets.get("request_id").strip()

if not question:
    raise ValueError("question parameter is required")

if not request_id:
    raise ValueError("request_id parameter is required")

job_result = run_job(question, request_id)

scorecard_html = ""
run_dir_path = Path(job_result["run_dir"])
scorecard_html_path = run_dir_path / "scorecard.html"
if scorecard_html_path.exists():
    scorecard_html = scorecard_html_path.read_text(encoding="utf-8")

result_payload = {
    "request_id": job_result["request_id"],
    "question": job_result["question"],
    "answer": job_result["answer"],
    "retrieved_chunks": job_result["retrieved_chunks"],
    "scorecard": job_result["scorecard"],
    "run_dir": job_result["run_dir"],
    "scorecard_json_path": job_result["scorecard_json_path"],
    "scorecard_html": scorecard_html,
}

print("request_id:", job_result["request_id"])
print("run_dir:", job_result["run_dir"])
print("answer_verdict:", job_result["scorecard"].get("answer_verdict"))
print("answer_trust_score:", job_result["scorecard"].get("answer_trust_score"))
print("overall_status:", job_result["scorecard"].get("overall_status"))
print("go_no_go:", job_result["scorecard"].get("go_no_go"))
print()
print(job_result["answer"])

dbutils.notebook.exit(json.dumps(result_payload))
