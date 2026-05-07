# Databricks notebook source
# MAGIC %pip install --upgrade "pydantic>=2.6,<3" "PyYAML>=6"
# MAGIC dbutils.library.restartPython()
# MAGIC

# COMMAND ----------

# One-shot backfill: read the silver chunks table, embed every chunk_text
# with the same embedding model that rag_answer_trust_job.py uses for
# query embedding, and write the result back as a new array<double>
# column.  Run this whenever the silver corpus changes (new chunks
# added, text revised, embedding model swapped).
#
# This notebook is the prerequisite for the vector-search retrieve_chunks
# in rag_answer_trust_job.py — that job validates that an `embedding`
# column exists and refuses to run otherwise.

import os
import sys
from pathlib import Path

REPO_ROOT = "/Workspace/Users/ethan.hall@kentro.us/ts-rnd-explainable-ai"
REPO_SRC = f"{REPO_ROOT}/src"

if REPO_SRC not in sys.path:
    sys.path.insert(0, REPO_SRC)

os.environ["OPENAI_API_KEY"] = dbutils.secrets.get("dbss-wvu-poc", "openai-key")

print("REPO_ROOT exists:", Path(REPO_ROOT).exists())


# COMMAND ----------

from pyspark.sql.types import ArrayType, DoubleType, StructField, StructType

from trusted_ai_toolkit.config import load_config
from trusted_ai_toolkit.model_client import embed_texts, resolve_embedding_model_name


# COMMAND ----------

CONFIG_PATH = f"{REPO_ROOT}/config.yaml"

CATALOG = "wvu"
SCHEMA = "ethanhall"
SILVER_TABLE = f"{CATALOG}.{SCHEMA}.silver_chunks"

# Column name to write embeddings into.  Must match EMBEDDING_COLUMN
# in rag_answer_trust_job.py — change both together if renamed.
EMBEDDING_COLUMN = "embedding"

# First matching column wins.  rag_answer_trust_job uses the same lookup
# order downstream; keep them aligned.
TEXT_COLUMN_CANDIDATES = ("chunk_text", "text", "snippet", "content")

# Batch size for embedding API calls.  text-embedding-3-small accepts
# up to 2048 inputs per call; 256 keeps the request body small enough
# to retry cleanly on transient failure without losing too much work.
EMBED_BATCH_SIZE = 256

base_cfg = load_config(Path(CONFIG_PATH))
cfg = base_cfg.model_copy(
    update={
        "adapters": base_cfg.adapters.model_copy(
            update={
                "provider": "openai_compatible",
                "endpoint": "https://api.openai.com/v1",
                "api_key_env": "OPENAI_API_KEY",
                # request_format is ignored by embed_texts but the schema
                # requires a value — keep it consistent with the runtime
                # job.
                "request_format": "responses",
            }
        )
    }
)

embedding_model = resolve_embedding_model_name(cfg)
print("silver table:    ", SILVER_TABLE)
print("embedding column:", EMBEDDING_COLUMN)
print("embedding model: ", embedding_model)


# COMMAND ----------

df = spark.table(SILVER_TABLE)
print("current columns:", df.columns)

text_col = next((c for c in TEXT_COLUMN_CANDIDATES if c in df.columns), None)
if text_col is None:
    raise ValueError(
        f"silver table has no text-bearing column; expected one of "
        f"{TEXT_COLUMN_CANDIDATES}, got {df.columns}"
    )
print("text column:", text_col)

if EMBEDDING_COLUMN in df.columns:
    print(
        f"WARNING: '{EMBEDDING_COLUMN}' column already exists on {SILVER_TABLE}; "
        "this run will overwrite every value with a fresh embedding from "
        f"{embedding_model}.  Cancel now if that is not what you want."
    )


# COMMAND ----------

# Materialise to pandas for batch embedding.  This silver table is
# expected to be small (< 100k rows in the POC).  For a production-scale
# corpus, replace this with a pandas_udf or per-partition foreach.
pdf = df.toPandas()
print("rows to embed:", len(pdf))

if len(pdf) == 0:
    raise ValueError(f"silver table {SILVER_TABLE} is empty; nothing to embed")


# COMMAND ----------

texts = pdf[text_col].fillna("").astype(str).tolist()

embeddings: list[list[float]] = []
for i in range(0, len(texts), EMBED_BATCH_SIZE):
    batch = texts[i : i + EMBED_BATCH_SIZE]
    result = embed_texts(batch, cfg)
    if len(result.embeddings) != len(batch):
        raise ValueError(
            f"embed_texts returned {len(result.embeddings)} vectors for {len(batch)} "
            f"texts in batch starting at offset {i}"
        )
    embeddings.extend(result.embeddings)
    print(f"embedded {i + len(batch):>6} / {len(texts)}")

if len(embeddings) != len(pdf):
    raise ValueError(
        f"final vector count {len(embeddings)} does not match row count {len(pdf)}"
    )

# Sanity-check the dimensionality is consistent across rows.
dims = {len(v) for v in embeddings}
if len(dims) != 1:
    raise ValueError(f"inconsistent embedding dimensions: {dims}")
print("embedding dimension:", next(iter(dims)))


# COMMAND ----------

# Drop any pre-existing embedding column on the pandas frame before we
# attach the fresh values, so the schema rebuild below sees only one
# embedding field.
if EMBEDDING_COLUMN in pdf.columns:
    pdf = pdf.drop(columns=[EMBEDDING_COLUMN])
pdf[EMBEDDING_COLUMN] = embeddings

# Build a schema that mirrors the original table plus the embedding
# column, so Spark types stay stable across the round-trip.
existing_fields = [
    field for field in df.schema.fields if field.name != EMBEDDING_COLUMN
]
new_schema = StructType(
    existing_fields + [StructField(EMBEDDING_COLUMN, ArrayType(DoubleType()), True)]
)

# Reorder pandas columns to match the new schema's field order before
# spark.createDataFrame consumes it.
pdf = pdf[[field.name for field in new_schema.fields]]

new_df = spark.createDataFrame(pdf, schema=new_schema)

# overwriteSchema=true allows adding the new column on the Delta table.
# mergeSchema would also work but only appends — overwrite cleanly
# replaces stale embeddings on re-runs.
(
    new_df.write
        .mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(SILVER_TABLE)
)
print(
    f"wrote {len(pdf)} rows back to {SILVER_TABLE} with "
    f"'{EMBEDDING_COLUMN}' column ({next(iter(dims))}-dim {embedding_model})"
)


# COMMAND ----------

# Verify
verify_df = spark.table(SILVER_TABLE)
print("columns:        ", verify_df.columns)
print("row count:      ", verify_df.count())
print("first row keys: ", list(verify_df.limit(1).collect()[0].asDict().keys()))
print("vector preview: ", verify_df.limit(1).collect()[0][EMBEDDING_COLUMN][:5], "...")

