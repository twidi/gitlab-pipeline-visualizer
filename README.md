# GitLab Pipeline Visualizer

Visualize GitLab CI pipeline as a Mermaid diagram, showing either the execution timeline of jobs or the dependencies between them.

## Features

- Two visualization modes:
  - **Timeline**: Shows the execution timeline of jobs (default)
    
    ![Timeline visualization example](timeline-example.png)
  
  - **Dependencies**: Shows the dependencies between jobs
    
    ![Dependencies visualization example](dependencies-example.png)

- Multiple output formats:
  - Direct Mermaid diagram rendering
  - Mermaid.live URL for interactive editing
  - Kroki.io URL for PNG rendering
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

To run the web interface:

```bash
python app.py
```

Then visit `http://localhost:5000` in your browser.

The web interface requires:
- A GitLab pipeline URL
- A GitLab personal access token with `read_api` scope
- Selection of visualization mode and output format

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
