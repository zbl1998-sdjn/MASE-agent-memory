mkdir -p needlesets
cd needlesets
wget -c https://huggingface.co/datasets/amodaresi/NoLiMa/resolve/main/needlesets/needle_set.json
wget -c https://huggingface.co/datasets/amodaresi/NoLiMa/resolve/main/needlesets/needle_set_MC.json
wget -c https://huggingface.co/datasets/amodaresi/NoLiMa/resolve/main/needlesets/needle_set_ONLYDirect.json
wget -c https://huggingface.co/datasets/amodaresi/NoLiMa/resolve/main/needlesets/needle_set_hard.json
wget -c https://huggingface.co/datasets/amodaresi/NoLiMa/resolve/main/needlesets/needle_set_w_CoT.json
wget -c https://huggingface.co/datasets/amodaresi/NoLiMa/resolve/main/needlesets/needle_set_w_Distractor.json

cd ..
mkdir -p haystack/rand_shuffle
cd haystack/rand_shuffle
wget -c https://huggingface.co/datasets/amodaresi/NoLiMa/resolve/main/haystack/rand_shuffle/rand_book_1.txt
wget -c https://huggingface.co/datasets/amodaresi/NoLiMa/resolve/main/haystack/rand_shuffle/rand_book_2.txt
wget -c https://huggingface.co/datasets/amodaresi/NoLiMa/resolve/main/haystack/rand_shuffle/rand_book_3.txt
wget -c https://huggingface.co/datasets/amodaresi/NoLiMa/resolve/main/haystack/rand_shuffle/rand_book_4.txt
wget -c https://huggingface.co/datasets/amodaresi/NoLiMa/resolve/main/haystack/rand_shuffle/rand_book_5.txt

wget -c https://huggingface.co/datasets/amodaresi/NoLiMa/resolve/main/haystack/rand_shuffle_long/rand_book_1.txt
wget -c https://huggingface.co/datasets/amodaresi/NoLiMa/resolve/main/haystack/rand_shuffle_long/rand_book_2.txt
wget -c https://huggingface.co/datasets/amodaresi/NoLiMa/resolve/main/haystack/rand_shuffle_long/rand_book_3.txt
wget -c https://huggingface.co/datasets/amodaresi/NoLiMa/resolve/main/haystack/rand_shuffle_long/rand_book_4.txt
wget -c https://huggingface.co/datasets/amodaresi/NoLiMa/resolve/main/haystack/rand_shuffle_long/rand_book_5.txt