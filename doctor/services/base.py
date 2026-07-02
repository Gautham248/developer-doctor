from doctor.capabilities import Capability


class BaseService:
    """Base class for shared, testable system-access services (§12).

    Every service declares the single capability (§11) required to use
    it. DoctorPlugin.use_service() checks this against the calling
    plugin's declared `capabilities` before handing out an instance.
    """

    required_capability: Capability