export PYTHONPATH="../"
echo $$
python -u run_tests.py --config run_config/multi_test_config_book_250.yaml
python -u run_tests.py --config run_config/multi_test_config_book_500.yaml
python -u run_tests.py --config run_config/multi_test_config_book_1K.yaml
python -u run_tests.py --config run_config/multi_test_config_book_2K.yaml
python -u run_tests.py --config run_config/multi_test_config_book_4K.yaml
python -u run_tests.py --config run_config/multi_test_config_book_8K.yaml
python -u run_tests.py --config run_config/multi_test_config_book_16K.yaml
python -u run_tests.py --config run_config/multi_test_config_book_32K.yaml
