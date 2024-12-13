from pathlib import Path

import pillow_heif
from click import echo
from litellm import completion
from PIL import Image, ImageFile

from ncli.utils import prompt_user


# Register HEIF opener with Pillow
pillow_heif.register_heif_opener()

PROMPT_EXTRACT_TEXT = """
Please extract all text/information in this image as they are written.
Do not include additional commentary.
"""


def scan_images(
    dir_path: Path,
    auto_approve: bool,
):
    heic_files = list(dir_path.glob("*.heic")) + list(dir_path.glob("*.HEIC"))
    heic_files.sort()
    if not heic_files:
        echo(f"No HEIC files found in {dir_path}")
        return
    echo(f"Found HEIC files: {heic_files}")

    for heic_path in heic_files:
        try:
            txt_path = heic_path.with_suffix(".txt")
            if txt_path.exists():
                echo(f"Skipping {heic_path} - text file already exists")
                continue

            if not auto_approve and not prompt_user(f"Do you want to process '{heic_path}'?"):
                continue

            # Create corresponding text file path

            # Open the image using Pillow
            image = Image.open(heic_path)

            # Create message with the image
            response = completion(
                model="anthropic/claude-3-5-sonnet-20241022",
                max_tokens=4096,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful AI assistant.",
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": PROMPT_EXTRACT_TEXT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/jpeg;base64," + image_to_base64(image),
                                },
                            },
                        ],
                    },
                ],
            )

            echo(f"Response LLM: {response}")

            extracted_text = response.choices[0].message.content
            txt_path.write_text(extracted_text)

            echo(f"Saved text content to: {txt_path}")

        except Exception as e:
            echo(f"Error processing {heic_path.name}: {e!s}")


def image_to_base64(image: ImageFile):
    """Convert PIL Image to base64 string"""
    import base64
    import io

    # Convert to RGB if needed
    if image.mode != "RGB":
        image = image.convert("RGB")

    # Save image to bytes buffer
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")

    # Convert to base64
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def summarize_txt(
    dir_path: Path,
):
    txt_files = list(dir_path.glob("*.txt"))
    txt_files.sort()
    if not txt_files:
        echo(f"No txt files found in {dir_path}")
        return

    prompt = ""
    for txt_path in txt_files:
        content = txt_path.read_text()
        prompt += f"""
<file name="{txt_path.name}">
{content}
</file>
"""

    prompt += """
Based on all of the files above, can you create a CSV file containing all the information?
Group the values based on the shared field name or questions, and use them as the CSV headers.
Do not attempt to change things on your own and write per the original.
Also, please include the file name as the first column.

Please use quote to wrap the CSV values so that comma within the values do not break the format.

Do not include additional commentary and output only the resulting CSV.
"""

    response = completion(
        model="anthropic/claude-3-5-sonnet-20241022",
        max_tokens=8092,
        messages=[
            {
                "role": "system",
                "content": "You are a helpful AI assistant.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                ],
            },
        ],
    )

    response_metadata = {
        "id": response.id,
        "model": response.model,
        "object": response.object,
        "usage": response.usage,
        "finish_reason": response.choices[0].finish_reason,
    }
    echo(f"Response metadata: {response_metadata}")

    extracted_text = response.choices[0].message.content
    summary_file = dir_path / "summary.csv"
    summary_file.write_text(extracted_text)

    echo(f"Saved text content to: {summary_file}")
