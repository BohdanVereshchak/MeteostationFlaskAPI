"""Run from the project root: python -m tools.preview. No real services are used."""

from tools.demo_data import load_demo_app

if __name__ == "__main__":
    module = load_demo_app()
    print("Isolated Meteo preview: http://127.0.0.1:4302/web")
    module.app.run(host="127.0.0.1", port=4302, debug=False, use_reloader=False)
