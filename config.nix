{ lib, ... }:
{
  vars.backends.local = {
    get = ''
      cp /var/lib/vars/$1/$2 $out/
    '';
    set = ''
      mkdir -p /var/lib/vars/$1
      cp $in/$2 /var/lib/vars/$1/$2
    '';
    exists = ''
      test -e /var/lib/vars/$1/$2
    '';
    generators = lib.genAttrs [ "simple" "a" "b" ] (_: { });
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
