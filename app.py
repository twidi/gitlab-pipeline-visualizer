# app.py
from flask import Flask, jsonify, render_template, request

from gitlab_pipeline_visualizer import (
    DEFAULT_MERMAID_CONFIG,
    GitLabPipelineVisualizer,
    fetch_pipeline_data,
    parse_gitlab_url,
)

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html", default_config=DEFAULT_MERMAID_CONFIG)


@app.route("/visualize", methods=["POST"])
def visualize():
    try:
        # Get common form data
        mode = request.form.get("mode", "timeline")
        mermaid_config = request.form.get("mermaid_config", DEFAULT_MERMAID_CONFIG)

        # Determine input method and get pipeline data
        if "pipeline_data" in request.form:
            # Direct pipeline data input
            try:
                pipeline_data = request.json.get("pipeline_data")
                if not pipeline_data:
                    raise ValueError("Pipeline data is empty or invalid")
            except Exception as e:
                raise ValueError(f"Invalid pipeline data format: {str(e)}")
        else:
            # GitLab credentials input
            gitlab_url = request.form.get("url")
            gitlab_token = request.form.get("token")

            if not gitlab_url or not gitlab_token:
                raise ValueError(
                    "Both GitLab URL and token are required when not providing pipeline data"
                )

            # Parse the GitLab URL and fetch data
            base_url, project_path, pipeline_id = parse_gitlab_url(gitlab_url)
            pipeline_data = fetch_pipeline_data(
                base_url, gitlab_token, project_path, pipeline_id
            )

        # Create visualizer instance
        visualizer = GitLabPipelineVisualizer(
            pipeline_data,
            verbose=0,
        )

        # Generate diagram
        mermaid_content = visualizer.generate_mermaid_content(mode)

        # Generate all three formats
        return jsonify(
            {
                "mermaid": visualizer.generate_mermaid(mermaid_content, mermaid_config),
                "mermaid_live": visualizer.generate_mermaid_live_url(
                    mermaid_content, mermaid_config
                ),
                "kroki_io": visualizer.generate_kroki_io_url(
                    mermaid_content, mermaid_config
                ),
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    app.run(debug=True)
