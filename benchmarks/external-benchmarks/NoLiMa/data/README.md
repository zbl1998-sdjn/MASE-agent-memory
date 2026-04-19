### NoLiMa.data

This directory contains files that are either used in the haystack processing pipeline or to download the dataset.

For evaluation:
- `book_haystack.py`: The haystack class file that is used for needle placement in the main evaluation.
- `download_NoLiMa_data.sh`: A script to download the NoLiMa dataset from the HuggingFace Datasets.

For haystack processing:
- `download_books.sh`: A script to download the books from HuggingFace Datasets.
- `clean_books.ipynb`: A jupyter notebook that is used to clean the books: remove extra newlines, standardize styling, trim leading and trailing whitespaces, and other text refinements.
- `remove_distractors.ipynb`: A jupyter notebook that is used to remove distracting words from the books.
- `filtering_conflicts.70b.py`: A python script that is used to filter out conflicting information from the books. A manual step is required afterwards to audit the flagged conflicts and remove them.
- `random_book_gen_char.ipynb`: A jupyter notebook that is used to generate random books within a range of lines and characters.