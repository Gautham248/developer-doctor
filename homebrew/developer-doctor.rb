# frozen_string_literal: true

# Plugin-driven CLI that diagnoses developer workstations.
class DeveloperDoctor < Formula
  include Language::Python::Virtualenv

  desc "Plugin-driven CLI that diagnoses developer workstations"
  homepage "https://github.com/Gautham248/developer-doctor"
  url "https://github.com/Gautham248/developer-doctor/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "REPLACE_ME_AFTER_FIRST_RELEASE"
  license "MIT"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "Developer Doctor", shell_output("#{bin}/doctor --help")
  end
end
