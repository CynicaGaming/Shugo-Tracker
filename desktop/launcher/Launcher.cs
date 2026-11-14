// ShugoTracker.exe: a small launcher with the whole app inside it (app.zip).
// The first start of each version unpacks the app into the "app" folder next to the exe; every start after that
// just runs it, so starting takes about a second instead of unpacking ~250 MB each time.
// Built with the .NET Framework's csc (C# 5): see desktop/build-exe.ps1.
using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;

static class Launcher
{
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern int MessageBoxW(IntPtr hWnd, string text, string caption, uint type);

    static string Quote(string a)
    {
        if (a.Length > 0 && a.IndexOfAny(new[] { ' ', '\t', '"' }) < 0) return a;
        var sb = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in a)
        {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') sb.Append('\\', slashes * 2 + 1);
            else sb.Append('\\', slashes);
            slashes = 0;
            sb.Append(c);
        }
        sb.Append('\\', slashes * 2).Append('"');
        return sb.ToString();
    }

    static string Unpack(string baseDir, string build)
    {
        string appRoot = Path.Combine(baseDir, "app");
        string appDir = Path.Combine(appRoot, build);
        if (File.Exists(Path.Combine(appDir, ".complete"))) return appDir;
        Directory.CreateDirectory(appRoot);
        string tmp = appDir + ".unpacking-" + Process.GetCurrentProcess().Id;
        if (Directory.Exists(tmp)) Directory.Delete(tmp, true);
        using (Stream s = Assembly.GetExecutingAssembly().GetManifestResourceStream("app.zip"))
        using (var zip = new ZipArchive(s, ZipArchiveMode.Read))
            zip.ExtractToDirectory(tmp);
        File.WriteAllText(Path.Combine(tmp, ".complete"), build);
        try
        {
            if (Directory.Exists(appDir)) Directory.Delete(appDir, true);    // a half-finished earlier unpack
            Directory.Move(tmp, appDir);
        }
        catch (IOException)
        {
            if (!File.Exists(Path.Combine(appDir, ".complete"))) throw;      // another start finished first: fine
            try { Directory.Delete(tmp, true); } catch (Exception) { }
        }
        foreach (string d in Directory.GetDirectories(appRoot))              // older versions (skipped if still running)
            if (!string.Equals(d, appDir, StringComparison.OrdinalIgnoreCase))
                try { Directory.Delete(d, true); } catch (Exception) { }
        return appDir;
    }

    [STAThread]
    static int Main(string[] args)
    {
        string exe = Process.GetCurrentProcess().MainModule.FileName;
        string root = Path.GetDirectoryName(exe);
        try
        {
            string build;
            using (Stream s = Assembly.GetExecutingAssembly().GetManifestResourceStream("build.txt"))
            using (var r = new StreamReader(s))
                build = r.ReadToEnd().Trim();
            string appDir;
            try { appDir = Unpack(root, build); }
            catch (UnauthorizedAccessException)                                  // a folder we can't write to
            {
                appDir = Unpack(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                             "ShugoTracker"), build);
            }
            var sb = new StringBuilder();
            foreach (string a in args) sb.Append(sb.Length > 0 ? " " : "").Append(Quote(a));
            var psi = new ProcessStartInfo(Path.Combine(appDir, "Shugo Tracker.exe"), sb.ToString());
            psi.UseShellExecute = false;
            psi.WorkingDirectory = root;
            psi.EnvironmentVariables["PORTABLE_EXECUTABLE_FILE"] = exe;      // the app keeps its data next to this exe
            Process.Start(psi);
            return 0;
        }
        catch (Exception e)
        {
            MessageBoxW(IntPtr.Zero, "Shugo Tracker couldn't start:\n\n" + e.Message, "Shugo Tracker", 0x10);
            return 1;
        }
    }
}
