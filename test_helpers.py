class MockFunctionCallParams:
    """Mimics Pipecat's FunctionCallParams for testing."""
    def __init__(self, **kwargs):
        self.arguments = kwargs
