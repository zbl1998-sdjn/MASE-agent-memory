export VLLM_LOGGING_LEVEL=ERROR

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --model_name) MODEL_NAME="$2"; shift ;;
        --num_gpus) NUM_GPUS="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

if [ "$MODEL_NAME" = "CohereForAI/c4ai-command-r-plus-08-2024" ]; then
  export OMP_NUM_THREADS=1
fi

echo "$MODEL_NAME"
echo "$NUM_GPUS"

vllm serve "$MODEL_NAME" \
    --tensor-parallel-size "$NUM_GPUS" \
    --max-model-len 40000 \
    --max-seq-len-to-capture 38000 \
    --disable-log-stats
