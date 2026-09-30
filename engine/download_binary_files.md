huggingface-cli download google/gemma-4-12B-it \
    --include "*.safetensors" "config.json" "tokenizer.json" \
    --local-dir ./custom_engine_weights/ \
    --local-dir-use-symlinks False


Download the binary files once to a local directory:bash
huggingface-cli download google/gemma-4-12B-it \
    --include "*.safetensors" "config.json" "tokenizer.json" \
    --local-dir ./custom_engine_weights/ \
    --local-dir-use-symlinks False


Point the engine script directly to ./custom_engine_weights/. The load_file() script handles the ingestion, and the CUDA extensions process them locally in a private loop.
