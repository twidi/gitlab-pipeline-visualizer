import json

from flask import Flask, jsonify, render_template, request

from gitlab_pipeline_visualizer import (
    DEFAULT_MERMAID_CONFIG,
    GRAPHQL_QUERY,
    GitLabPipelineVisualizer,
    fetch_pipeline_data,
    get_query_variables,
    logger,
    parse_gitlab_url,
    setup_logging,
)

app = Flask(__name__)


setup_logging(0)


@app.route("/")
def index():
    # Get GraphQL query and variables template
    variables_template = get_query_variables("%(PROJECT_PATH)s", "%(PIPELINE_ID)s")

    # Convert to JSON strings for safe embedding in HTML
    variables_template_json = json.dumps(variables_template, indent=2)

    return render_template(
        "index.html",
        default_config=DEFAULT_MERMAID_CONFIG,
        graphql_query=GRAPHQL_QUERY,
        variables_template=variables_template_json,
    )


@app.route("/visualize", methods=["POST"])
def visualize():
    try:
        # Get common form data
        mode = request.form.get("mode", "timeline")
        mermaid_config = request.form.get("mermaid_config", DEFAULT_MERMAID_CONFIG)

        # Determine input method and get pipeline data
        if request.form.get("pipeline_data", "").strip():
            # Direct pipeline data input
            try:
                pipeline_data = request.form.get("pipeline_data")
                if not pipeline_data:
                    raise ValueError("Pipeline data is empty or invalid")
                pipeline_data = json.loads(pipeline_data)
            except Exception as e:
                raise ValueError(f"Invalid pipeline data format: {str(e)}")
        else:
            # GitLab credentials input
            gitlab_url = request.form.get("url")
            gitlab_token = request.form.get("token")

            if not gitlab_url or not gitlab_token:
                raise ValueError(
                    "Either the pipeline data or both GitLab URL and token are required when not providing pipeline data"
                )

            # Parse the GitLab URL and fetch data
            base_url, project_path, pipeline_id = parse_gitlab_url(gitlab_url)
            pipeline_data = fetch_pipeline_data(
                base_url, gitlab_token, project_path, pipeline_id
            )

        # Create visualizer instance
        visualizer = GitLabPipelineVisualizer(
            pipeline_data,
        )

        # Generate diagram
        mermaid_content = visualizer.generate_mermaid_content(mode)

        # Generate all three formats
        return jsonify(
            {
                "raw": visualizer.generate_mermaid(mermaid_content, mermaid_config),
                "editUrl": visualizer.generate_mermaid_live_url(
                    mermaid_content, mermaid_config, "edit"
                ),
                "viewUrl": visualizer.generate_mermaid_live_url(
                    mermaid_content, mermaid_config, "view"
                ),
            }
        )

    except Exception as e:
        logger.exception(e)
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    app.run(debug=True)
