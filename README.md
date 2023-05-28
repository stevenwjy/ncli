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

We suggest using [poetry](https://python-poetry.org/) for managing this project. If you don't have it yet, install it
using the command below:

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

ncli allows you to export the following data for books in your Audible library:

- List of chapters
- Clips
- Notes
- Accompanying PDF

Execute the following command to do so:

```
ncli audible export --target <path>

# To fetch all book data, even if they have been indexed before, use:
ncli audible export --target <path> --renew
```

The target path should be a directory where you want the Audible data to be stored.

To set a standard path for your Audible exports and avoid having to put it in every command, use the following:

```
ncli config set audible_export_dir <path>
```

Your data will be organized in a markdown file, except for the accompanying PDF (if any), which will be saved as a
separate file.

Currently, we do not support retrieving bookmarks and notes for non-book content (e.g., podcasts).

To see what exported data might look like, check out the [`examples/audible`](./examples/audible) directory.

### Kindle

ncli allows you to export the following Kindle data:

- Highlights
- Notes

Execute the following command to do so:

```
ncli kindle export --target <path>

# To fetch all book data, even if they have been indexed before, use:
ncli kindle export --target <path> --renew
```

The target path should be a directory where you want the Kindle data to be stored.

To set a standard path for your Kindle exports and avoid having to put it in every command, use the following:

```
ncli config set kindle_export_dir <path>
```

Please be aware of these known limitations (which also apply to [Kindle Notebook](https://read.amazon.com/notebook)):

- Highlighted images and tables cannot be exported. You can only retrieve the page location.
- Formatting for the highlights and notes may not be preserved perfectly (including newlines).
- Some highlights may be hidden or truncated due to export limits imposed by Kindle's
  [clipping limit](https://www.amazonforum.com/s/question/0D54P00006zJWGuSAO).

This feature was initially inspired by the [kindle-highlights](https://github.com/speric/kindle-highlights) project.

To see what exported data might look like, check out the [`examples/kindle`](./examples/kindle) directory.

### Notion

For Notion, ncli supports formatting exported data for efficient tracking with version control systems like Git.

```
ncli notion export --target <path> --source <path>

# To overwrite an existing target path:
ncli notion export --force --target <path> --source <path>
```

The target path should be a directory where you want the Notion data to be stored. The source path should point to the
exported zip file, which you can obtain by following the guide for
[Export as Markdown & CSV](https://www.notion.so/help/export-your-content#export-as-markdown-&-csv).

To set a standard path for your Notion exports and avoid having to put it in every command, use the following:

```
ncli config set notion_export_dir <path>
```

To see what exported data might look like, check out the [`examples/notion`](./examples/notion) directory.

### YouTube

ncli offers the ability to:

- Retrieve transcript
- Summarize using AI

Here's how:

```
ncli youtube export --target <path> --source <url>

# To summarize the transcript (or group them by time window):
ncli youtube export --target <path> --summarize -- source <url>
```

The target path should be a directory where you want the YouTube data to be stored.

To set a standard path for your YouTube exports and avoid having to put it in every command, use the following:

```
ncli config set youtube.export_dir <path>
```

By default, the `--summarize` option groups transcripts within a given time window, which is useful if you plan to
perform the summarization elsewhere. If you want to call the API directly, adjust the config:

```
# Note that you also need to set the `OPENAI_API_KEY` env var accordingly
ncli config set youtube.model <model>
```

Refer to the documentation [here](https://platform.openai.com/docs/models) for available models.

You can also adjust the system and summarize prompts using `youtube.prompt_system` and `youtube.prompt_summarize` config
keys. We currently use a relatively simple pattern:

```
messages=[
  {"role": "system", "content": config.prompt_system},
  {"role": "user", "content": f'Transcript:\n"""\n{text}\n"""\n\n{config.prompt_summarize}'},
]
```

Note that the transcript text has been sanitized to remove newlines and unnecessary whitespaces.

By default, we use a 15-minute time window for summarizing, as longer time windows sometimes do not fit into the GPT-4
8K context window. You can customize this time window by updating the config:

```
ncli config set youtube.summary_time_window_minutes <int>
```

To see what exported data might look like, check out the [`examples/youtube`](./examples/youtube) directory.

## FAQ

**1. Why are there more than one licenses in this repository?**

This repository includes code based on other open-source projects, which are bound by stricter licenses, such as
AGPL-3.0. This license requires any derivative work to adopt the same license. However, parts of the code that don't
rely on such libraries are covered under the MIT license.

For instance, Amazon-related features (i.e., [Kindle](#kindle) and [Audible](#audible)) rely on the
[audible](https://github.com/mkb79/Audible) package (under AGPL-3.0) to retrieve Amazon auth cookies and fetch Audible
data.

**2. What's the purpose of this project?**

In today's information-rich world, managing and accessing notes scattered across multiple platforms can be challenging.
The primary goal of this project is to aid users in consolidating their notes in a single location, making it easier to
track changes with an existing version control system such as Git.

This project doesn't aim to replace the excellent user experience provided by many services. Instead, it serves as a
complementary tool for version control, local search, data backup, and more.

## Contributing

We warmly welcome all contributions. Please submit bug reports and feature requests through GitHub Issues. We appreciate
your time and effort in helping to improve this project!
