import json

from flask import Flask, jsonify, render_template, request
from flask_cors import cross_origin

from gitlab_pipeline_visualizer import (
    DEFAULT_MERMAID_CONFIG,
    GitLabPipelineVisualizer,
    fetch_pipeline_data,
    logger,
    parse_gitlab_url,
    prepare_graphql_query,
    setup_logging,
)

app = Flask(__name__)


setup_logging(0)


@app.route("/")
def index():
    return render_template(
        "index.html",
        default_config=DEFAULT_MERMAID_CONFIG,
    )


@app.route("/get_query")
@cross_origin(methods=["GET"])
def get_query():
    try:
        project_path = request.args.get("project_path")
        pipeline_id = request.args.get("pipeline_id")
        next_page_cursor = request.args.get("next_page_cursor")
    except Exception as e:
        logger.exception(e)
        return jsonify({"error": "Missing parameters"}), 400

    data = {
        "graphql_query": prepare_graphql_query(
            project_path, pipeline_id, next_page_cursor
        ),
    }

    return jsonify(data)


@app.route("/visualize", methods=["POST"])
@cross_origin(methods=["POST"])
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
                "jpgUrl": visualizer.generate_mermaid_ink_url(
                    mermaid_content, mermaid_config, "jpg"
                ),
                "pngUrl": visualizer.generate_mermaid_ink_url(
                    mermaid_content, mermaid_config, "png"
                ),
                "svgUrl": visualizer.generate_mermaid_ink_url(
                    mermaid_content, mermaid_config, "svg"
                ),
                "webpUrl": visualizer.generate_mermaid_ink_url(
                    mermaid_content, mermaid_config, "webp"
                ),
                "pdfUrl": visualizer.generate_mermaid_ink_url(
                    mermaid_content, mermaid_config, "pdf"
                ),
            }
        )

    except Exception as e:
        logger.exception(e)
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    app.run(debug=True)
