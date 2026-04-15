{ lib, ... }:
{
  var.backend-local = {
    enable = true;
    directory = "/tmp/vars";
    vars = [
      "simple"
      "a"
      "b"
    ];
  };

  vars.generators = {
    simple = {
      files.simple = { };
      script = ''
        echo simple > "$out"/simple
      '';
    };
    a = {
      files.a = { };
      script = ''
        echo a > "$out"/a
      '';
    };
    b = {
      dependencies = [ "a" ];
      files.b = { };
      script = ''
        cat "$in"/a/a > "$out"/b
        echo b >> "$out"/b
      '';
    };
  };
}
