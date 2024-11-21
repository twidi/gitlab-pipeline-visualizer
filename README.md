# GitLab Pipeline Visualizer

Visualize GitLab CI pipeline as a Mermaid diagram, showing either the execution timeline of jobs or the dependencies between them.

## Features

- Two visualization modes:
  - **Timeline**: Shows the execution timeline of jobs (default)
    
    ![Timeline visualization example](timeline-example.png)
  
  - **Dependencies**: Shows the dependencies between jobs
    
    ![Dependencies visualization example](dependencies-example.png)

- Multiple output formats:
  - Raw Mermaid diagram rendering
  - Url for interactive viewing on Mermaid.live
  - Url for interactive editing on Mermaid.live
- Customizable Mermaid configuration
- Available as both CLI tool and web interface

## Installation

1. Clone the repository:
```bash
git clone https://github.com/twidi/gitlab-pipeline-visualizer.git
cd gitlab-pipeline-visualizer
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Command Line Interface

```bash
python gitlab-pipeline-visualizer.py https://gitlab.com/group/project/-/pipelines/123
```

To switch between visualization mode, use `--mode` (`timeline` (the default if not given) or `deps`)

To switch between output, use `--output` (`raw`, `view` (url to mermaid.live) or `edit` (url to mermaid.live))

The GitLab token can be provided in three ways (in order of precedence):
1. Command line argument `--token`
2. Environment variable `GITLAB_TOKEN`
3. Configuration file

Configuration files can be placed in:
- Windows: `%APPDATA%/gitlab-pipeline-visualizer/config`
- Unix: `$XDG_CONFIG_HOME/gitlab-pipeline-visualizer/config` (or `~/.config/gitlab-pipeline-visualizer/config`)
- Or: `~/.gitlab-pipeline-visualizer`

Example config file (INI format):
```ini
[gitlab]
token = glpat-XXXXXXXXXXXXXXXXXXXX

# Optional: override default Mermaid configuration
[mermaid]
config = 
    layout: elk
    theme: dark
    gantt:
      useWidth: 1000
```

### Web Interface

A web interface is available that provides a user-friendly way to generate pipeline visualizations. It uses the same core functionality as the CLI version.

An online version exists at https://gitlabviz.pythonanywhere.com/


The interface:

![Timeline visualization example](web-example1.png)

With the result:

![Timeline visualization example](web-example2.png)

Possibility to not use a gitlab token asking to run the GraphQL query:

![Timeline visualization example](web-example3.png)

Example of usage of the Gitlab GraphQL query explorer:

![Timeline visualization example](web-example4.png)

With the result from a GraphQL query:

![Timeline visualization example](web-example5.png)


To run the web interface:

```bash
python app.py
```

Then visit `http://localhost:5000` in your browser.

The web interface requires:
- A GitLab pipeline URL
- A GitLab personal access token with `read_api` scope
- Selection of visualization mode and output format


### Browser Addon

A browser extension is available to automatically display pipeline visualizations directly on GitLab pipeline web pages.

Note that the addon is currently not packaged or published to any browser extension stores - it can only be used locally as an unpacked extension in developer mode.

#### Installation

1. Clone the repository if you haven't already
2. Enable Developer Mode in your browser's extensions settings
3. Load the unpacked extension by pointing your browser to the `browser-addon/firefox-or-chrom/manifest.json` file in the repository

#### Configuration

By default, the addon connects to https://gitlabviz.pythonanywhere.com/ for generating visualizations. You can customize this in the addon preferences:

1. Access the addon options/preferences through your browser's extension management interface
2. Update the "Server URL" field to point to your preferred visualization server
3. Save the changes

This configuration option allows you to use a different server instance if you're running your own deployment or want to use an alternative hosted version.


## Requirements

- Python 3.10+
- `requests` library
- Flask (for web interface)

## Development

1. Clone the repository:
```bash
git clone https://github.com/twidi/gitlab-pipeline-visualizer.git
cd gitlab-pipeline-visualizer
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Author

Created by [Claude sonnet 3.5](https://claude.ai) with the help of [Twidi](https://github.com/twidi)

## Links

- [Source Code](https://github.com/twidi/gitlab-pipeline-visualizer/)
- [Online version](https://gitlabviz.pythonanywhere.com/)
