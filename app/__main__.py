from textual.app import App
from .screen.scr_dashboard import DashboardScreen


class ChesterApp(App):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def on_mount(self):
        """Set up the initial screen and services."""
        # Initialize the dashboard screen
        dashboard_screen = DashboardScreen()
        self.push_screen(dashboard_screen)


if __name__ == "__main__":
    app = ChesterApp()
    app.run()
