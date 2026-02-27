import argparse
import json
import pdfplumber


def parse_slides(input_path: str, output_path: str) -> None:
    slides = []
    with pdfplumber.open(input_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            slides.append({"slide": i, "text": text.strip()})

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(slides, f, ensure_ascii=False, indent=2)

    print(f"Extracted {len(slides)} slides → {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract text from PDF slides")
    parser.add_argument("--input", required=True, help="Path to the PDF file")
    parser.add_argument("--output", required=True, help="Path to the output JSON file")
    args = parser.parse_args()
    parse_slides(args.input, args.output)
