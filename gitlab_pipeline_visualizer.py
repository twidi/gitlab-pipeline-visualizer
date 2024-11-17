#!/usr/bin/env python

import argparse
import base64
import configparser
import json
import logging
import os
import re
import sys
import traceback
import webbrowser
import zlib
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from operator import itemgetter
from pathlib import Path
from pprint import pprint
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
              stages {
                nodes {
                  name
                }
              }
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

        return data["data"]["project"]["pipeline"]

    def deduplicate_jobs(self, jobs):
        """Handle multiple runs of the same job, numbering them and adjusting dependencies.

        For multiple runs of the same job:
        - Add numbered suffixes to identifiers (job_1, job_2, etc.)
        - Force each run after the first to depend on the previous run
        - For jobs depending on a duplicated job, select the last run that ended before
          the dependent job starts

        Args:
            jobs (list): List of job dictionaries

        Returns:
            list: Updated list of jobs with adjusted identifiers and dependencies
        """
        job_runs = defaultdict(list)
        processed_jobs = []

        # First pass: group jobs by base identifier and add numbered suffixes
        for job in jobs:
            base_identifier = job["identifier"]
            runs = job_runs[base_identifier]
            run_number = len(runs) + 1

            # Create a new job with numbered identifier
            new_job = job.copy()
            new_job["base_identifier"] = base_identifier
            new_job["identifier"] = f"{base_identifier}_{run_number}"

            # Force dependency on previous run (except for first run)
            if run_number > 1:
                new_job["needs"] = [f"{base_identifier}_{run_number-1}"]

            runs.append(new_job)
            processed_jobs.append(new_job)

        # Second pass: update dependencies for jobs that depend on duplicated jobs
        for job in processed_jobs:
            updated_needs = []
            job_start = job["startedAt"]

            for need in job["needs"]:
                if need in job_runs:  # This is a duplicated job
                    # Get all runs that ended before this job started (or all, in case we don't have some)
                    eligible_runs = [
                        run
                        for run in job_runs[need]
                        if run["finishedAt"] and run["finishedAt"] < job_start
                    ] or job_runs
                    updated_needs.append(eligible_runs[-1]["identifier"])
                else:
                    # Non-duplicated job - keep as is
                    updated_needs.append(need)

            job["needs"] = updated_needs

        return processed_jobs

    def get_ordered_stages(self, pipeline_data):
        """Get ordered list of stages, including .pre and .post."""
        # Get stages from pipeline data
        stages = [stage["name"] for stage in pipeline_data["stages"]["nodes"]]

        # Check for .pre and .post in jobs
        job_stages = set(job["stage"]["name"] for job in pipeline_data["jobs"]["nodes"])

        # Add .pre at the beginning if it exists in jobs
        if ".pre" in job_stages:
            stages.insert(0, ".pre")

        # Add .post at the end if it exists in jobs
        if ".post" in job_stages:
            stages.append(".post")

        return stages

    def build_dependency_graph(self, jobs, ordered_stages):
        """Build a complete dependency graph combining explicit needs and stage-based dependencies.

        Args:
            jobs (dict): Dictionary of job data, keyed by job identifier
            ordered_stages (list): List of stages in order

        Returns:
            dict: Graph of job dependencies where each key is a job identifier and each value
                  is a list of job identifiers it depends on
        """
        dependencies = {}

        # Create mapping of stages to jobs
        stage_jobs = defaultdict(list)
        for job_id, job in jobs.items():
            stage_jobs[job["stage"]].append(job_id)

        for job_id, job in jobs.items():
            # Start with explicit needs
            job_deps = set(job["needs"])

            # If no explicit needs and not in first stage, depend on all jobs from previous stage
            if not job_deps and job["stage"] in ordered_stages:
                stage_idx = ordered_stages.index(job["stage"])
                if stage_idx > 0:
                    # Look for the nearest previous stage that has jobs
                    for prev_stage in reversed(ordered_stages[:stage_idx]):
                        if prev_stage in stage_jobs:
                            job_deps.update(stage_jobs[prev_stage])
                            break

            dependencies[job_id] = list(job_deps)

        return dependencies

    def remove_transitive_dependencies(self, jobs):
        """Remove transitive dependencies from job dependencies.

        If job C depends on jobs A and B, and B also depends on A,
        then we can remove A from C's dependencies since it's redundant.

        Args:
            jobs (dict): Dictionary of job data including dependencies

        Returns:
            dict: Updated jobs dictionary with transitive dependencies removed
        """
        # Create a deep copy to avoid modifying the original
        updated_jobs = deepcopy(jobs)

        # For each job
        for job in updated_jobs.values():
            direct_deps = set(job["needs"])
            indirect_deps = set()

            # Find all indirect dependencies
            for dep in direct_deps:
                if dep in updated_jobs:
                    indirect_deps.update(updated_jobs[dep]["needs"])

            # Remove indirect dependencies from direct dependencies
            job["needs"] = list(direct_deps - indirect_deps)

        return updated_jobs

    def name_to_identifier(self, name):
        return re.sub(r"\W+|^(?=\d)", "_", name)

    def str_to_datetime(self, str_datetime):
        return (
            datetime.fromisoformat(str_datetime.replace("Z", "+00:00"))
            if str_datetime
            else None
        )

    def normalize_jobs(self, jobs_data):
        """Simplify jobs data and order them by `queuedAt`, removing alls that are not in success/failed status"""
        return sorted(
            [
                job
                | {
                    "queuedAt": self.str_to_datetime(job["queuedAt"]),
                    "startedAt": self.str_to_datetime(job["startedAt"]),
                    "finishedAt": self.str_to_datetime(job["finishedAt"]),
                    "identifier": self.name_to_identifier(job["name"]),
                    "stage": job["stage"]["name"],
                    "needs": (
                        [
                            self.name_to_identifier(node["name"])
                            for node in job["needs"]["nodes"]
                        ]
                        if job.get("needs", {}).get("nodes", [])
                        else []
                    ),
                }
                for job in jobs_data
                if job["status"] in ("SUCCESS", "FAILED") and job.get("queuedAt")
            ],
            key=itemgetter("queuedAt"),
        )

    def process_pipeline_data(self):
        """Process pipeline data and extract dependencies and job information."""
        pipeline_data = self.fetch_pipeline_data()
        jobs_data = pipeline_data["jobs"]["nodes"]

        # Get ordered stages
        ordered_stages = self.get_ordered_stages(pipeline_data)

        # Normalize the jobs
        jobs = self.normalize_jobs(jobs_data)
        jobs = self.deduplicate_jobs(jobs)
        jobs_dict = {job["identifier"]: job for job in jobs}
        jobs_dict = self.remove_transitive_dependencies(jobs_dict)
        dependencies = self.build_dependency_graph(jobs_dict, ordered_stages)
        return ordered_stages, jobs_dict, dependencies

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
        stages, jobs, dependencies = self.process_pipeline_data()

        failed_jobs = [
            job_id for job_id, job in jobs.items() if job["status"] == "FAILED"
        ]

        mermaid = [
            "stateDiagram-v2",
            "",
        ]

        # Add style definitions for failed jobs if any exist
        if failed_jobs:
            mermaid.extend(
                [
                    "    %% Style definitions",
                    "    classDef failed fill:#f2dede,stroke:#a94442,color:#a94442",
                    "",
                ]
            )

        # Start pipeline container
        mermaid.extend(
            [
                f'    state "Dependencies of Pipeline {self.pipeline_id}" as pipeline {{',
                "",
                "    %% States with duration",
            ]
        )

        # Add job states with duration
        for job_id, job in jobs.items():
            mermaid.append(
                f'    state "{job["name"]}<br>{self.format_duration(job["duration"])}" as {job_id}'
            )

        mermaid.append("")
        mermaid.append("    %% Dependencies")

        # Add dependencies
        for job_id, job in jobs.items():
            if not dependencies.get(job_id, []):
                # Jobs with no dependencies start from [*]
                mermaid.append(f"    [*] --> {job_id}")
            else:
                # Add each dependency relationship
                for dep in dependencies[job_id]:
                    mermaid.append(f"    {dep} --> {job_id}")

        # Close the pipeline state
        mermaid.append("    }")

        # Add class declarations for failed jobs after the state definition
        for job_id in failed_jobs:
            mermaid.append(f"class {job_id} failed")

        return "\n".join(mermaid)

    def calculate_job_order(self, jobs, dependencies):
        """Calculate execution order of jobs based on dependencies and start times.

        Args:
            jobs (dict): Dictionary of jobs with their details including startedAt times
            dependencies (dict): Dictionary mapping job IDs to lists of dependency job IDs

        Returns:
            list: Job identifiers in execution order
        """
        # Start with jobs that have no dependencies
        independent_jobs = [
            job_id
            for job_id in jobs
            if job_id not in dependencies or not dependencies[job_id]
        ]

        # Sort independent jobs by start time
        independent_jobs.sort(
            key=lambda job_id: (jobs[job_id]["startedAt"] or datetime.max)
        )

        ordered_jobs = []
        processed_jobs = set()

        def process_job_and_dependents(job_id):
            if job_id in processed_jobs:
                return

            processed_jobs.add(job_id)
            ordered_jobs.append(job_id)

            # Find jobs that depend on this one
            dependents = []
            for dependent_id, deps in dependencies.items():
                if job_id in deps and dependent_id not in processed_jobs:
                    dependents.append(dependent_id)

            # Sort dependents by readiness (how many of their dependencies are processed)
            # and start time
            def dependency_readiness(dependent_id):
                deps = dependencies.get(dependent_id, [])
                deps_ready = sum(1 for d in deps if d in processed_jobs)
                start_time = jobs[dependent_id]["startedAt"] or datetime.max
                return (deps_ready / len(deps) if deps else 1, start_time)

            dependents.sort(key=dependency_readiness, reverse=True)

            # Process dependents that have all dependencies met
            for dependent_id in dependents:
                if all(dep in processed_jobs for dep in dependencies[dependent_id]):
                    process_job_and_dependents(dependent_id)

        # Process all independent jobs and their dependents
        for job_id in independent_jobs:
            process_job_and_dependents(job_id)

        return ordered_jobs

    def generate_mermaid_timeline(self):
        """Generate a Mermaid Gantt chart showing pipeline execution timeline."""
        stages, jobs, dependencies = self.process_pipeline_data()

        # Find earliest start time
        start_times = [
            job["startedAt"] for job in jobs.values() if job["startedAt"] is not None
        ]
        if not start_times:
            raise ValueError("No jobs with timing information found")

        pipeline_start = min(start_times)

        # Basic Gantt chart setup
        mermaid = [
            "gantt",
            f"    title Timeline of Pipeline {self.pipeline_id}",
            "    dateFormat  HH:mm:ss",
            "    axisFormat  %H:%M:%S",
            "",
            "    section Jobs",
        ]

        # Get jobs in execution order
        ordered_jobs = self.calculate_job_order(jobs, dependencies)

        # Helper to format job status for Mermaid
        def format_job_status(job):
            if "status" in job:
                return "crit" if job["status"] == "FAILED" else "active"
            return ""

        # Add each job to the timeline
        for job_id in ordered_jobs:
            job = jobs[job_id]

            if job["startedAt"] and job["finishedAt"]:
                # Calculate relative start time from pipeline start
                relative_start = (job["startedAt"] - pipeline_start).total_seconds()

                start_time = f"{int(relative_start // 3600):02d}:{int((relative_start % 3600) // 60):02d}:{int(relative_start % 60):02d}"
                formatted_duration = self.format_duration(job["duration"])

                status = format_job_status(job)
                status_part = f"{status}, " if status else ""
                mermaid.append(
                    f"    {job['name']} {formatted_duration:<10} :{status_part}{job_id}, {start_time}, {job['duration']}s"
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
        print(
            f"Error generating diagram:: {e}, {traceback.format_exc()}", file=sys.stderr
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
