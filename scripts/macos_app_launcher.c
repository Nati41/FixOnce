#include <errno.h>
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
/*
  FixOnce macOS .app launcher (Mach-O)

  Why:
  - LaunchServices/Finder often refuses to launch a .app whose CFBundleExecutable is a shell script.
  - It reports: kLSNoExecutableErr (-10827) even when the script exists.

  What:
  - This small native launcher locates the project root relative to the app bundle location
    and execs python to run scripts/app_launcher.py.

  Assumptions:
  - FixOnce.app lives inside the FixOnce repo root (project root).
    (project root = parent directory of FixOnce.app)
*/

static int is_executable(const char *path) {
  return (path && access(path, X_OK) == 0);
}

static const char *pick_python(void) {
  static const char *candidates[] = {
      "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3",
      "/usr/local/bin/python3",
      "/opt/homebrew/bin/python3",
      NULL,
  };
  for (int i = 0; candidates[i]; i++) {
    if (is_executable(candidates[i])) return candidates[i];
  }
  return "python3";
}

static void die(const char *msg) {
  // Finder won't show stderr, but this helps when launching from Terminal.
  int e = errno;
  const char *es = strerror(e);
  fprintf(stderr, "FixOnce launcher error: %s (errno=%d: %s)\n", msg, e, es);

  // Also append to a log file for Finder launches.
  const char *home = getenv("HOME");
  if (home && *home) {
    char log_path[PATH_MAX];
    if (snprintf(log_path, sizeof(log_path), "%s/Library/Logs/FixOnce-launcher.log", home) <
        (int)sizeof(log_path)) {
      FILE *f = fopen(log_path, "a");
      if (f) {
        time_t now = time(NULL);
        struct tm tm_now;
        localtime_r(&now, &tm_now);
        char ts[64];
        strftime(ts, sizeof(ts), "%Y-%m-%d %H:%M:%S", &tm_now);
        fprintf(f, "[%s] %s (errno=%d: %s)\n", ts, msg, e, es);
        fclose(f);
      }
    }
  }
  _exit(1);
}

static int file_exists(const char *path) {
  return (path && access(path, R_OK) == 0);
}

int main(int argc, char **argv) {
  (void)argc;
  (void)argv;

  char exe_path[PATH_MAX];
  uint32_t size = sizeof(exe_path);
  if (_NSGetExecutablePath(exe_path, &size) != 0) {
    die("_NSGetExecutablePath failed");
  }

  char resolved[PATH_MAX];
  if (!realpath(exe_path, resolved)) {
    die("realpath(executable) failed");
  }

  // resolved: .../FixOnce.app/Contents/MacOS/FixOnce
  char macos_dir[PATH_MAX];
  strncpy(macos_dir, resolved, sizeof(macos_dir));
  macos_dir[sizeof(macos_dir) - 1] = '\0';
  char *macos_dirname = dirname(macos_dir); // .../Contents/MacOS

  char contents_dir[PATH_MAX];
  strncpy(contents_dir, macos_dirname, sizeof(contents_dir));
  contents_dir[sizeof(contents_dir) - 1] = '\0';
  char *contents_dirname = dirname(contents_dir); // .../Contents

  char app_dir[PATH_MAX];
  strncpy(app_dir, contents_dirname, sizeof(app_dir));
  app_dir[sizeof(app_dir) - 1] = '\0';
  char *app_dirname = dirname(app_dir); // .../FixOnce.app

  char project_dir[PATH_MAX];
  strncpy(project_dir, app_dirname, sizeof(project_dir));
  project_dir[sizeof(project_dir) - 1] = '\0';
  char *project_dirname = dirname(project_dir); // parent of FixOnce.app

  const char *python = pick_python();

  // Find the repo root by walking up until scripts/app_launcher.py exists.
  // This allows FixOnce.app to live inside nested folders within the repo.
  char repo_root[PATH_MAX];
  strncpy(repo_root, project_dirname, sizeof(repo_root));
  repo_root[sizeof(repo_root) - 1] = '\0';

  char launcher_py[PATH_MAX];
  int found = 0;
  for (int i = 0; i < 8; i++) {
    if (snprintf(launcher_py, sizeof(launcher_py), "%s/scripts/app_launcher.py",
                 repo_root) >= (int)sizeof(launcher_py)) {
      die("launcher path too long");
    }
    if (file_exists(launcher_py)) {
      found = 1;
      break;
    }
    // Move up one directory
    char tmp[PATH_MAX];
    strncpy(tmp, repo_root, sizeof(tmp));
    tmp[sizeof(tmp) - 1] = '\0';
    const char *parent = dirname(tmp);
    if (!parent || strcmp(parent, repo_root) == 0) break;
    strncpy(repo_root, parent, sizeof(repo_root));
    repo_root[sizeof(repo_root) - 1] = '\0';
  }

  if (!found) {
    die("could not locate scripts/app_launcher.py relative to FixOnce.app");
  }

  if (chdir(repo_root) != 0) {
    die("chdir(repo_root) failed");
  }

  // argv for exec: python3 <launcher.py>
  char *const exec_argv[] = {(char *)python, launcher_py, NULL};
  execvp(python, exec_argv);
  die("execvp(python) failed");
  return 1;
}

