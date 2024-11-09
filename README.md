# ncli

CLI for exporting and synthesizing notes into Git-trackable files.

Table of contents:

- [Basics](#basics)
  - [Get Started](#get-started)
  - [Config](#config)
- [Features](#features)
  - [Audible](#audible)
  - [Kindle](#kindle)
  - [Notion](#notion)
  - [YouTube](#youtube)
- [FAQ](#faq)
- [Contributing](#contributing)

## Basics

### Get Started

Start by cloning the repository and navigating into the directory:

```bash
git clone https://github.com/stevenwjy/ncli.git
cd ncli
```

It is recommended to use [poetry](https://python-poetry.org/) for managing this project. If you don't have it yet,
install it with the following command:

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

Next, install the dependencies and enter a shell to start using the CLI:

```bash
poetry install

# Inside the shell, the `ncli` executable will be available for use.
poetry shell
```

### Config

**List**

To view all your configurations, including default values, use:

```bash
ncli config list
```

**Set**

To set a configuration, use the following command:

```bash
ncli config set <key> <value>
# Example: `ncli config set youtube.language en`
```

Your configuration file is located at `~/.ncli/config.toml`. Customizing the configuration file path is not currently
supported.

Note that your configuration file may appear shorter than the output of the list command. This is because we avoid
writing default configuration values.

**Amazon Auth**

Setting up Amazon Authentication is simple:

```bash
# Run the command below and follow the interactive prompts.
ncli config amazon-auth
```

On successful registration, you'll see a message like `Successfully registered Name's Audible for iPhone.` This is
because we use the [audible](https://github.com/mkb79/Audible) package for authentication.

## Features

### Audible

**Export notes**

Included information: list of chapters, clips, notes, and accompanying PDF.

```bash
ncli audible export --target <path>

# To fetch all book data, even if previously indexed:
ncli audible export --target <path> --renew
```

The target path should be a directory where you want the Audible data to be stored.

To set a standard path for your Audible exports and avoid having to specify it in every command:

```bash
ncli config set audible_export_dir <path>

# Once configured:
ncli audible export
```

Your data will be organized in a Markdown file, with any accompanying PDF saved as a separate file.

Currently, we do not support retrieving bookmarks and notes for non-book content (e.g., podcasts).

To see example output, check out the [`examples/audible`](./examples/audible) directory.

**Download audiobook**

Download audiobook (`.aaxc` file), convert to `.mp3`, and split by chapter (e.g., for side-loading on
[Snipd](https://www.snipd.com)).

> [!IMPORTANT]
> Please only use this for accessing your own audiobooks and DO NOT upload them publicly.

Prerequisites:

- Book must be indexed first using the `export` command above
- `ffmpeg` and `ffprobe` must be installed
  ([installation guide](https://github.com/KwaiVGI/LivePortrait/blob/main/assets/docs/how-to-install-ffmpeg.md))

Assuming you have `audible_export_dir` set, you can run:

```bash
# Interactive prompts will guide you through
ncli audible download
```

By convention, audio files are stored in `/path/to/audible_export_dir/audio/book_title`. Contributions to add more
granular configuration options are welcome.

### Kindle

**Export highlights and notes**

```bash
ncli kindle export --target <path>

# To fetch all book data, even if they have been indexed before, use:
ncli kindle export --target <path> --renew
```

The target path should be a directory where you want the Kindle data to be stored.

To set a standard path for your Kindle exports and avoid having to put it in every command, use the following:

```bash
ncli config set kindle_export_dir <path>

# Afterward, you can simply use:
ncli kindle export
```

Please be aware of these known limitations (which also apply to [Kindle Notebook](https://read.amazon.com/notebook)):

- Highlighted images and tables cannot be exported. You can only retrieve the page location.
- Formatting for the highlights and notes may not be preserved perfectly (including newlines).
- Some highlights may be hidden or truncated due to export limits imposed by Kindle's
  [clipping limit](https://www.amazonforum.com/s/question/0D54P00006zJWGuSAO).

This feature was initially inspired by the [kindle-highlights](https://github.com/speric/kindle-highlights) project.

To see what exported data might look like, check out the [`examples/kindle`](./examples/kindle) directory.

### Notion

**Post-process Notion's exported data**

```bash
ncli notion export --target <path> --source <path>

# To overwrite an existing target path:
ncli notion export --force --target <path> --source <path>
```

The target path should be a directory where you want the Notion data to be stored. The source path should point to the
exported zip file, which you can obtain by following the guide for
[Export as Markdown & CSV](https://www.notion.so/help/export-your-content#export-as-markdown-&-csv).

To set a standard path for your Notion exports and avoid having to put it in every command, use the following:

```bash
ncli config set notion_export_dir <path>
```

To see what exported data might look like, check out the [`examples/notion`](./examples/notion) directory.

### YouTube

**Summarize video**

```bash
ncli youtube export --target <path> --summarize --source <url>

# To also include the transcript:
ncli youtube export --target <path> --summarize --transcribe --source <url>
```

The target path should be a directory where you want the YouTube data to be stored.

To set a standard path for your YouTube exports and avoid having to put it in every command, use the following:

```bash
ncli config set youtube.export_dir <path>

# Afterward, you can simply use:
ncli youtube export --summarize --source <url>
```

Currently, ncli only supports summarization with OpenAI. Contributions to add support for other providers are welcome.

The `--summarize` option requires setting the `OPENAI_API_KEY` environment variable. Without this option, ncli will only
concatenate transcript items within the configured time window (future plan: implement a proper chunking algorithm).
This can be useful though if you plan to perform summarization elsewhere.

```bash
# For the complete list of default values, see Config class in 'ncli/kit_youtube.py'

ncli config set youtube.language "en"
ncli config set youtube.model "gpt-4o-mini"
ncli config set youtube.prompt_system "system prompt"
ncli config set youtube.prompt_summarize "user prompt"
ncli config set youtube.summary_time_window_minutes 15
```

For available models, refer to the [OpenAI documentation](https://platform.openai.com/docs/models).

The prompt pattern uses a simple structure:

```py
messages=[
  {"role": "system", "content": config.prompt_system},
  {"role": "user", "content": f"<transcript>:\n{text}\n</transcript>\n\n{config.prompt_summarize}"},
]
```

To see example output, check out the [`examples/youtube`](./examples/youtube) directory.

## FAQ

**1. Why are there more than one license in this repository?**

ncli currently depends on some code with an AGPL-3.0 license, which requires any derivative work to adopt the same
license. More specifically, Amazon-related features (i.e., [Kindle](#kindle) and [Audible](#audible)) rely on the
[audible](https://github.com/mkb79/Audible) package (under AGPL-3.0) to retrieve Amazon auth cookies and fetch Audible
data.

Code that doesn't rely on such libraries is covered under the MIT license.

**2. What's the purpose of this project?**

The primary goal of this project is to help those who want to organize their notes in a single location and track
changes with a version control system such as Git.

## Contributing

All contributions are welcome. Please submit bug reports and feature requests through GitHub Issues. Thanks for your
time and effort in helping to improve this project!
