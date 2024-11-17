#!/usr/bin/env python

import argparse
import base64
import configparser
import json
import logging
import os
import sys
import webbrowser
import zlib
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from textwrap import dedent, indent
from urllib.parse import urlparse

import requests

DEFAULT_MERMAID_CONFIG = """\
layout: elk
gantt:
  useWidth: 1600
"""


class GitLabPipelineVisualizer:
    def __init__(
        self,
        project_path,
        pipeline_id,
        gitlab_token,
        gitlab_url="https://gitlab.com",
        verbose=0,
        mode="timeline",
        mermaid_config=None,
    ):
        self.project_path = project_path
        self.pipeline_id = pipeline_id
        self.headers = {
            "Authorization": f"Bearer {gitlab_token}",
            "Content-Type": "application/json",
        }
        self.gitlab_url = gitlab_url
        self.mode = mode
        self.mermaid_config = mermaid_config or DEFAULT_MERMAID_CONFIG
        self.setup_logging(verbose)

    def setup_logging(self, verbose):
        self.logger = logging.getLogger("GitLabPipelineVisualizer")
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

        if verbose >= 1:
            self.logger.setLevel(logging.INFO)
        if verbose >= 2:
            self.logger.setLevel(logging.DEBUG)

    def fetch_pipeline_data(self):
        """Fetch pipeline data using GraphQL."""
        query = """
        query GetPipelineJobs($projectPath: ID!, $pipelineId: CiPipelineID!) {
          project(fullPath: $projectPath) {
            pipeline(id: $pipelineId) {
              jobs {
                nodes {
                  name
                  status
                  stage {
                    name
                  }
                  needs {
                    nodes {
                      name
                    }
                  }
                  startedAt
                  finishedAt
                  duration
                  queuedAt
                }
              }
            }
          }
        }
        """

        variables = {
            "projectPath": self.project_path,
            "pipelineId": f"gid://gitlab/Ci::Pipeline/{self.pipeline_id}",
        }

        url = f"{self.gitlab_url}/api/graphql"
        self.logger.info(f"\nPOST {url}")
        self.logger.info(f"Query Variables: {json.dumps(variables, indent=2)}")

        response = requests.post(
            url, headers=self.headers, json={"query": query, "variables": variables}
        )
        response.raise_for_status()

        data = response.json()
        self.logger.debug(f"\nResponse: {json.dumps(data, indent=2)}")

        return data["data"]["project"]["pipeline"]["jobs"]["nodes"]

    def remove_transitive_dependencies(self, dependencies):
        """Remove transitive dependencies from the graph."""
        # Get the full transitive closure
        closure = self.compute_transitive_closure(dependencies)

        # Create a new graph with only direct dependencies
        direct_deps = deepcopy(dependencies)

        for job, deps in dependencies.items():
            for dep in deps[:]:
                for other_dep in deps:
                    if other_dep != dep and dep in closure.get(other_dep, []):
                        if dep in direct_deps[job]:
                            direct_deps[job].remove(dep)

        return direct_deps

    def compute_transitive_closure(self, dependencies):
        """Compute the transitive closure of the dependency graph."""
        closure = deepcopy(dependencies)
        jobs = list(
            set(
                [job for job in dependencies.keys()]
                + [dep for deps in dependencies.values() for dep in deps]
            )
        )

        for k in jobs:
            for i in jobs:
                if i in closure and k in closure[i]:
                    for j in jobs:
                        if k in closure and j in closure[k]:
                            if i not in closure:
                                closure[i] = []
                            if j not in closure[i]:
                                closure[i].append(j)
        return closure

    def deduplicate_jobs(self, jobs_data):
        """Deduplicate jobs by name, keeping only the last run based on queuedAt time."""
        job_runs = defaultdict(list)

        # Group jobs by name
        for job in jobs_data:
            if job["queuedAt"]:
                queued_at = datetime.fromisoformat(
                    job["queuedAt"].replace("Z", "+00:00")
                )
                job_runs[job["name"]].append((queued_at, job))

        # Keep only the last run of each job
        deduplicated_jobs = []
        for job_name, runs in job_runs.items():
            # Sort runs by queuedAt time and keep the latest
            sorted_runs = sorted(runs, key=lambda x: x[0])
            if sorted_runs:
                deduplicated_jobs.append(sorted_runs[-1][1])

        return deduplicated_jobs

    def process_pipeline_data(self):
        """Process pipeline data and extract dependencies and job information."""
        jobs_data = self.fetch_pipeline_data()

        # Deduplicate jobs before processing
        jobs_data = self.deduplicate_jobs(jobs_data)

        raw_dependencies = defaultdict(list)
        job_statuses = {}
        job_details = {}
        stages = defaultdict(list)
        jobs_with_deps = set()

        # Filter out jobs that didn't run
        running_jobs = [
            job
            for job in jobs_data
            if job["status"] not in ["CREATED", "SKIPPED", "MANUAL"]
        ]

        for job in running_jobs:
            job_name = job["name"]
            job_statuses[job_name] = job["status"].lower()

            # Store job timing details
            details = {"stage": job["stage"]["name"]}
            if job["duration"] is not None:
                details["duration"] = job["duration"]
            if job["startedAt"]:
                details["started_at"] = job["startedAt"]
            if job["finishedAt"]:
                details["finished_at"] = job["finishedAt"]
            job_details[job_name] = details

            # Process needs (dependencies)
            if job["needs"]["nodes"]:
                for need in job["needs"]["nodes"]:
                    need_name = need["name"]
                    raw_dependencies[job_name].append(need_name)
                    jobs_with_deps.add(job_name)
                    jobs_with_deps.add(need_name)

            # Only add to stages if it has no dependencies
            if job_name not in jobs_with_deps:
                stages[job["stage"]["name"]].append(job_name)

        # Remove transitive dependencies
        dependencies = self.remove_transitive_dependencies(raw_dependencies)

        return dependencies, job_statuses, job_details, stages, jobs_with_deps

    def wrap_mermaid_config(self, config_str):
        """Wrap the config in the required Mermaid format."""
        config_str = indent(dedent(config_str).strip("\n"), "  ")
        return f"---\nconfig:\n{config_str}\n---\n"

    def format_duration(self, duration_seconds):
        """Format duration in a Mermaid-friendly way: (Xmn SS) or (SS)"""
        minutes = int(duration_seconds // 60)
        seconds = int(duration_seconds % 60)

        if minutes == 0:
            return f"({seconds}s)"
        else:
            return f"({minutes}mn {seconds:02d})"

    def generate_mermaid_deps(self):
        """Generate a Mermaid state diagram representation of the pipeline dependencies."""
        dependencies, job_statuses, job_details, stages, jobs_with_deps = (
            self.process_pipeline_data()
        )

        mermaid = [
            "stateDiagram-v2",
            "",
            "    %% Style definitions",
            "    classDef failed fill:#f2dede,stroke:#a94442,color:#a94442",
            "",
            f'    state "Dependencies of Pipeline {self.pipeline_id}" as pipeline {{',
            "",
        ]

        # Keep track of failed jobs
        failed_jobs = []

        # First add entry points - jobs with no dependencies that others depend on
        root_jobs = set()
        for job in dependencies:
            for dep in dependencies[job]:
                if dep not in dependencies and dep in job_statuses:
                    root_jobs.add(dep)

        # Add transitions from [*] to root jobs
        for job in sorted(root_jobs):
            if "duration" in job_details[job]:
                duration = self.format_duration(job_details[job]["duration"])
                mermaid.append(f"    [*] --> {job}")
                mermaid.append(f'    state "{job}<br>{duration}" as {job}')
                if job_statuses[job] == "failed":
                    failed_jobs.append(job)

        # Add dependencies
        for job, deps in sorted(dependencies.items()):
            if job in job_statuses:
                # Add job state definition with duration
                if "duration" in job_details[job]:
                    duration = self.format_duration(job_details[job]["duration"])
                    mermaid.append(f'    state "{job}<br>{duration}" as {job}')
                    if job_statuses[job] == "failed":
                        failed_jobs.append(job)

                # Add dependencies
                for dep in sorted(deps):
                    if dep in job_statuses:
                        mermaid.append(f"    {dep} --> {job}")

        # Add independent jobs at the end, sorted by start time
        independent_jobs = []
        for job_name, details in job_details.items():
            if (
                job_name not in dependencies
                and job_name not in root_jobs
                and not any(job_name in deps for deps in dependencies.values())
            ):
                if "started_at" in details:
                    start_time = datetime.fromisoformat(
                        details["started_at"].replace("Z", "+00:00")
                    )
                    independent_jobs.append((start_time, job_name))

        if independent_jobs:
            mermaid.append("")
            mermaid.append("    %% Independent jobs")
            for _, job_name in sorted(independent_jobs):
                if "duration" in job_details[job_name]:
                    duration = self.format_duration(job_details[job_name]["duration"])
                    mermaid.append(
                        f'    state "{job_name}<br>{duration}" as {job_name}'
                    )
                    if job_statuses[job_name] == "failed":
                        failed_jobs.append(job_name)

        # Close the pipeline state
        mermaid.append("    }")

        # Add class declarations for failed jobs after the state definition
        for job in failed_jobs:
            mermaid.append(f"class {job} failed")

        return "\n".join(mermaid)

    def calculate_job_order(self, dependencies, job_details):
        """Calculate the order of jobs based on dependencies and start times."""
        # Start with jobs that have no dependencies
        independent_jobs = [
            name
            for name in job_details
            if name not in dependencies or not dependencies[name]
        ]

        # Sort independent jobs by start time
        independent_jobs.sort(
            key=lambda job: (
                datetime.fromisoformat(
                    job_details[job]["started_at"].replace("Z", "+00:00")
                )
                if "started_at" in job_details[job]
                else datetime.max
            )
        )

        ordered_jobs = []
        processed_jobs = set()

        def add_job_and_dependents(job):
            if job in processed_jobs:
                return
            processed_jobs.add(job)
            ordered_jobs.append(job)

            # Find all jobs that depend on this job
            dependents = []
            for dependent, deps in dependencies.items():
                if job in deps and dependent not in processed_jobs:
                    dependents.append(dependent)

            # Sort dependents by how many of their dependencies are already processed
            def dependency_readiness(dep_job):
                deps = dependencies.get(dep_job, [])
                deps_ready = sum(1 for d in deps if d in processed_jobs)
                all_deps = len(deps)
                # If all dependencies are ready, use start time as tiebreaker
                if deps_ready == all_deps:
                    start_time = (
                        datetime.fromisoformat(
                            job_details[dep_job]["started_at"].replace("Z", "+00:00")
                        )
                        if "started_at" in job_details[dep_job]
                        else datetime.max
                    )
                    return (deps_ready / all_deps if all_deps else 1, start_time)
                return (deps_ready / all_deps if all_deps else 1, datetime.max)

            dependents.sort(key=dependency_readiness, reverse=True)

            # Process dependents that have all their dependencies met
            for dependent in dependents:
                if all(dep in processed_jobs for dep in dependencies[dependent]):
                    add_job_and_dependents(dependent)

        # Process all independent jobs and their dependents
        for job in independent_jobs:
            add_job_and_dependents(job)

        return ordered_jobs

    def generate_mermaid_timeline(self):
        """Generate a Mermaid Gantt chart representation of the pipeline timeline."""
        dependencies, job_statuses, job_details, stages, jobs_with_deps = (
            self.process_pipeline_data()
        )

        # Find pipeline start time
        start_times = [
            datetime.fromisoformat(details["started_at"].replace("Z", "+00:00"))
            for details in job_details.values()
            if "started_at" in details
        ]
        if not start_times:
            raise ValueError("No jobs with timing information found")

        pipeline_start = min(start_times)

        mermaid = [
            "gantt",
            f"    title Timeline of Pipeline {self.pipeline_id}",
            "    dateFormat  HH:mm:ss",
            "    axisFormat  %H:%M:%S",
            "",
            "    section Jobs",
        ]

        def format_job_status(status):
            """Return the Mermaid status tag for a job based on its status"""
            if status == "success":
                return "active"
            elif status == "failed":
                return "crit"
            return ""

        # Get ordered jobs
        ordered_jobs = self.calculate_job_order(dependencies, job_details)

        # Add jobs in the calculated order
        for job_name in ordered_jobs:
            details = job_details[job_name]

            if job_name not in dependencies or not dependencies[job_name]:
                # Independent job - use relative start time
                if "started_at" in details and "duration" in details:
                    job_start = datetime.fromisoformat(
                        details["started_at"].replace("Z", "+00:00")
                    )
                    relative_start = (job_start - pipeline_start).total_seconds()
                    start_time = f"{int(relative_start // 3600):02d}:{int((relative_start % 3600) // 60):02d}:{int(relative_start % 60):02d}"
                    formatted_duration = self.format_duration(details["duration"])
                    status_tag = format_job_status(job_statuses[job_name])
                    status_part = f"{status_tag}, " if status_tag else ""
                    mermaid.append(
                        f"    {job_name} {formatted_duration:<10} :{status_part}{job_name}, {start_time}, {details['duration']}s"
                    )
            else:
                # Dependent job - use after syntax
                if "duration" in details:
                    deps_str = " and ".join(dependencies[job_name])
                    formatted_duration = self.format_duration(details["duration"])
                    status_tag = format_job_status(job_statuses[job_name])
                    status_part = f"{status_tag}, " if status_tag else ""
                    mermaid.append(
                        f"    {job_name} {formatted_duration:<10} :{status_part}{job_name}, after {deps_str}, {details['duration']}s"
                    )

        return "\n".join(mermaid)

    def generate_mermaid_diagram(self):
        """Generate a Mermaid diagram based on the selected mode."""
        wrapped_config = self.wrap_mermaid_config(self.mermaid_config)
        if self.mode == "deps":
            return wrapped_config + self.generate_mermaid_deps()
        elif self.mode == "timeline":
            return wrapped_config + self.generate_mermaid_timeline()
        else:
            raise ValueError(f"Unsupported mode: {self.mode}")


def get_config_paths():
    """Get configuration file paths based on the OS."""
    if os.name == "nt":  # Windows
        config_home = os.environ.get(
            "APPDATA", str(Path.home() / "AppData" / "Roaming")
        )
        paths = [
            Path(config_home) / "gitlab-pipeline-visualizer" / "config",
            Path.home() / ".gitlab-pipeline-visualizer",
        ]
    else:  # Unix-like
        xdg_config_home = os.environ.get(
            "XDG_CONFIG_HOME", str(Path.home() / ".config")
        )
        paths = [
            Path(xdg_config_home) / "gitlab-pipeline-visualizer" / "config",
            Path.home() / ".gitlab-pipeline-visualizer",
        ]

    return paths


def get_config():
    """
    Get configuration from config file.
    Returns: configparser.ConfigParser object
    """
    config = configparser.ConfigParser()

    for config_path in get_config_paths():
        if config_path.is_file():
            config.read(config_path)
            break

    return config


def get_token():
    """
    Get GitLab token from environment or config file.
    Returns: token string or None if not found
    """
    # Check environment variable
    token = os.environ.get("GITLAB_TOKEN")
    if token:
        return token

    # Check config files
    config = get_config()
    try:
        return config["gitlab"]["token"]
    except (KeyError, configparser.Error):
        return None


def get_mermaid_config():
    """
    Get Mermaid configuration from config file or use default.

    Returns: mermaid config string
    """
    config = get_config()
    try:
        config_str = config["mermaid"]["config"].strip()
    except (KeyError, configparser.Error):
        config_str = DEFAULT_MERMAID_CONFIG
    return config_str


def prepare_mermaid_config(config_str, allow_elk_layout=True):
    """Return the mermaid config string

    Optionally filter out ELK layout configuration for services that don't support it.

    Args:
        config_str (str): The mermaid configuration
        allow_elk_layout (bool): Whether to allow ELK layout in the configuration.
                                Should be False for services like kroki.io that don't support it.

    """
    if not allow_elk_layout:
        # Split into lines, filter out any line containing both "layout" and "elk",
        # and rejoin the remaining lines
        lines = config_str.split("\n")
        lines = [
            line
            for line in lines
            if not ("layout" in line.lower() and "elk" in line.lower())
        ]
        config_str = "\n".join(lines)

    return config_str


def parse_gitlab_url(url):
    """
    Parse a GitLab pipeline URL to extract gitlab url, project path and pipeline ID.
    Example URL: https://gitlab.com/magency/products/iva/-/pipelines/1543446796

    Returns: (gitlab_url, project_path, pipeline_id)
    Raises: ValueError if URL format is invalid
    """
    # Parse the URL
    parsed = urlparse(url)

    # Get gitlab url
    gitlab_url = f"{parsed.scheme}://{parsed.netloc}"

    # Split the path into components and remove empty strings
    path_parts = [p for p in parsed.path.split("/") if p]

    # Check if path matches expected format:
    # [project_parts...] '-' 'pipelines' pipeline_id
    try:
        pipeline_index = path_parts.index("pipelines")
        if pipeline_index < 2 or path_parts[pipeline_index - 1] != "-":
            raise ValueError()

        # Pipeline ID is the last component
        pipeline_id = path_parts[pipeline_index + 1]
        if not pipeline_id.isdigit():
            raise ValueError()

        # Project path is everything before the '-'
        project_path = "/".join(path_parts[: pipeline_index - 1])

        return gitlab_url, project_path, pipeline_id

    except (ValueError, IndexError):
        raise ValueError(
            "Invalid GitLab pipeline URL path format. "
            "Expected format: https://GITLAB_HOST/GROUP/PROJECT/-/pipelines/PIPELINE_ID"
        )


def generate_mermaid_live_url(mermaid_content):
    """Generate a URL for mermaid.live with the diagram content."""

    # Create the state object expected by mermaid.live
    state = {
        "code": mermaid_content,
        "mermaid": '{"theme":"default"}',
        "autoSync": True,
        "updateDiagram": True,
    }

    # Encode the state object
    json_str = json.dumps(state)
    base64_str = base64.urlsafe_b64encode(json_str.encode()).decode().rstrip("=")

    return f"https://mermaid.live/edit#{base64_str}"


def generate_kroki_io_url(mermaid_content):
    """Generate a URL for kroki.io PNG rendering."""

    # Deflate and base64 encode the content as required by kroki
    deflated = zlib.compress(mermaid_content.encode("utf-8"))
    encoded = base64.urlsafe_b64encode(deflated).decode().rstrip("=")

    return f"https://kroki.io/mermaid/png/{encoded}"


def open_url_in_browser(url):
    """Open URL in the default web browser."""

    webbrowser.open(url)


def main():
    parser = argparse.ArgumentParser(
        description="""
Visualize GitLab CI pipeline as a Mermaid diagram.

Two visualization modes are available:
- timeline: shows the execution timeline of jobs (default)
- deps: shows the dependencies between jobs
""",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=f"""
The GitLab token can be provided in three ways (in order of precedence):
1. Command line argument --token
2. Environment variable GITLAB_TOKEN
3. Configuration file in one of these locations:
   - Windows: %APPDATA%/gitlab-pipeline-visualizer/config
   - Unix: $XDG_CONFIG_HOME/gitlab-pipeline-visualizer/config (or ~/.config/gitlab-pipeline-visualizer/config)
   - Or: ~/.gitlab-pipeline-visualizer

A default Mermaid configuration is provided:
{DEFAULT_MERMAID_CONFIG}
This configuration can be overridden in the config file.

Config file example (INI format):
--------------------------------
[gitlab]
token = glpat-XXXXXXXXXXXXXXXXXXXX

# Optional: override default Mermaid configuration
[mermaid]
config = 
    layout: elk
    theme: dark
    gantt:
      useWidth: 1000
--------------------------------

Note: The mermaid configuration must be indented under the 'config =' line.
If the [mermaid] section is omitted, the default configuration shown above will be used.

The config will be automatically wrapped in the required Mermaid format:
---
config:
  [your configuration]
---

Created by Claude sonnet 3.5 (https://claude.ai) with the help of Twidi (https://github.com/twidi)
Source code: https://github.com/twidi/gitlab-pipeline-visualizer/
Onlive version: https://gitlabviz.pythonanywhere.com/
""",
    )

    parser.add_argument(
        "url",
        help="GitLab pipeline URL (e.g., https://gitlab.com/group/project/-/pipelines/123)",
    )
    parser.add_argument("--token", help="GitLab private token")
    parser.add_argument(
        "--mode",
        choices=["timeline", "deps"],
        default="timeline",
        help="visualization mode: timeline (default) or deps",
    )
    parser.add_argument(
        "--output",
        choices=["mermaid", "mermaid.live", "kroki.io"],
        default="mermaid",
        help="""output format:
- mermaid: raw mermaid document (default)
- mermaid.live: URL to edit diagram on mermaid.live
- kroki.io: URL to render diagram as PNG using kroki.io""",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="open the URL in your default web browser (only valid with mermaid.live or kroki.io output)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="increase verbosity (use -v for URLs, -vv for full API responses)",
    )

    args = parser.parse_args()

    # Validate --open usage
    if args.open and args.output == "mermaid":
        parser.error(
            "--open option can only be used with mermaid.live or kroki.io output"
        )

    # Get token from args, env, or config
    token = args.token or get_token()
    if not token:
        print(
            "Error: GitLab token not found. Provide it via --token argument, GITLAB_TOKEN environment variable, or configuration file.",
            file=sys.stderr,
        )
        parser.print_help()
        sys.exit(1)

    try:
        gitlab_url, project_path, pipeline_id = parse_gitlab_url(args.url)

        # Get Mermaid config from config file or use default
        mermaid_config = prepare_mermaid_config(
            get_mermaid_config(), allow_elk_layout=args.output != "kroki.io"
        )

        visualizer = GitLabPipelineVisualizer(
            project_path,
            pipeline_id,
            token,
            gitlab_url,
            args.verbose,
            args.mode,
            mermaid_config,
        )

        # Get the mermaid diagram content
        mermaid_content = visualizer.generate_mermaid_diagram()

        # Handle different output formats
        url = None
        if args.output == "mermaid":
            print(mermaid_content)
        elif args.output == "mermaid.live":
            url = generate_mermaid_live_url(mermaid_content)
            print(url)
        elif args.output == "kroki.io":
            url = generate_kroki_io_url(mermaid_content)
            print(url)

        # Open URL in browser if requested
        if args.open and url:
            open_url_in_browser(url)

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"Error accessing GitLab API: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error generating diagram: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
