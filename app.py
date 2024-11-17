# app.py
from flask import Flask, jsonify, render_template, request

from gitlab_pipeline_visualizer import (DEFAULT_MERMAID_CONFIG,
                                        GitLabPipelineVisualizer,
                                        generate_kroki_io_url,
                                        generate_mermaid_live_url,
                                        parse_gitlab_url,
                                        prepare_mermaid_config)

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html", default_config=DEFAULT_MERMAID_CONFIG)


@app.route("/visualize", methods=["POST"])
def visualize():
    try:
        # Get form data
        gitlab_url = request.form["url"]
        gitlab_token = request.form["token"]
        mode = request.form.get("mode", "timeline")
        output_format = request.form.get("output", "mermaid")
        mermaid_config = prepare_mermaid_config(
            request.form.get("mermaid_config", DEFAULT_MERMAID_CONFIG),
            allow_elk_layout=output_format != "kroki.io",
        )

        # Parse the GitLab URL
        base_url, project_path, pipeline_id = parse_gitlab_url(gitlab_url)

        # Create visualizer instance
        visualizer = GitLabPipelineVisualizer(
            project_path,
            pipeline_id,
            gitlab_token,
            base_url,
            verbose=0,
            mode=mode,
            mermaid_config=mermaid_config,
        )

        # Generate diagram
        mermaid_content = visualizer.generate_mermaid_diagram()

        # Handle different output formats
        if output_format == "mermaid":
            return jsonify({"type": "mermaid", "content": mermaid_content})
        elif output_format == "mermaid.live":
            url = generate_mermaid_live_url(mermaid_content)
            return jsonify({"type": "url", "content": url})
        elif output_format == "kroki.io":
            url = generate_kroki_io_url(mermaid_content)
            return jsonify({"type": "url", "content": url})

    except Exception as e:
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    app.run(debug=True)
