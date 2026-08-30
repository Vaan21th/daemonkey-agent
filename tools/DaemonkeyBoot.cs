using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;

// Daemonkey 薄壳 · 双击后立刻画闪屏，再拉 powershell 跑肉。
// 改图不用重编（读 assets/skins）；改本文件才跑 tools/build-boot-exe.ps1。
internal static class DaemonkeyBoot
{
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern IntPtr FindWindow(string cls, string title);
    [DllImport("user32.dll")]
    static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")]
    static extern bool ShowWindow(IntPtr h, int n);

    static Mutex _mutex;
    static Label _hint;
    static Process _meat;
    static DateTime _failAt = DateTime.MinValue;
    static DateTime _startAt;
    static int _limitSec;
    static string _cmdFile;
    static int _barPos;
    static int _barDir = 1;
    static Panel _barFill;

    [STAThread]
    static void Main()
    {
        string root = Path.GetDirectoryName(Application.ExecutablePath);
        try { Run(root); }
        catch (Exception ex)
        {
            try { Stamp(root, "boot-crash " + ex.Message); } catch { }
            try { MessageBox.Show(ex.ToString(), "Daemonkey 启动失败"); } catch { }
        }
        try { Stamp(root, "boot-exit"); } catch { }
    }

    static void Run(string root)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);

        if (string.IsNullOrEmpty(root)) root = Environment.CurrentDirectory;
        Directory.SetCurrentDirectory(root);
        Stamp(root, "boot-start");

        string meat = Path.Combine(root, "daemonkey-launcher.ps1");
        if (!File.Exists(meat))
        {
            MessageBox.Show("找不到 daemonkey-launcher.ps1\r\n启动器文件不完整 · 请重新解压完整包。",
                "Daemonkey", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        string mutexName = "Local\\Daemonkey-" + ShortHash(root.TrimEnd('\\').ToLowerInvariant());
        bool created;
        _mutex = new Mutex(true, mutexName, out created);
        if (!created)
        {
            Stamp(root, "already-running");
            ActivateExisting();
            return;
        }

        string skinId = ReadSkin(root);
        bool firstBoot = !File.Exists(Path.Combine(root, ".venv", "Scripts", "python.exe"));
        bool daimon = skinId == "daimon";
        Color bg = daimon ? Color.FromArgb(253, 251, 246) : Color.FromArgb(15, 16, 24);
        Color foot = daimon ? Color.FromArgb(247, 240, 228) : Color.FromArgb(18, 19, 30);
        Color ink = daimon ? Color.FromArgb(67, 52, 34) : Color.White;
        Color muted = daimon ? Color.FromArgb(139, 115, 85) : Color.FromArgb(168, 174, 196);
        Color track = daimon ? Color.FromArgb(220, 200, 168) : Color.FromArgb(60, 70, 110);
        Color fill = daimon ? Color.FromArgb(201, 138, 75) : Color.FromArgb(124, 108, 240);

        var splash = new Form();
        splash.Text = "Daemonkey-splash";
        splash.FormBorderStyle = FormBorderStyle.None;
        splash.StartPosition = FormStartPosition.CenterScreen;
        splash.Size = new Size(480, 320);
        splash.BackColor = bg;
        splash.TopMost = true;
        splash.ShowInTaskbar = false;
        try { splash.Region = new Region(RoundPath(480, 320, 18)); } catch { }

        var mask = new Panel();
        mask.Size = new Size(480, 72);
        mask.Location = new Point(0, 248);
        mask.BackColor = foot;
        splash.Controls.Add(mask);

        var title = new Label();
        title.Text = "正在启动 Daemonkey";
        title.Font = new Font("Microsoft YaHei UI", 11f);
        title.ForeColor = ink;
        title.BackColor = foot;
        title.TextAlign = ContentAlignment.MiddleCenter;
        title.Size = new Size(480, 24);
        title.Location = new Point(0, 8);
        mask.Controls.Add(title);

        _hint = new Label();
        _hint.Text = firstBoot ? "第一次会慢一点 · 在准备运行环境" : "马上就好";
        _hint.Font = new Font("Microsoft YaHei UI", 9f);
        _hint.ForeColor = muted;
        _hint.BackColor = foot;
        _hint.TextAlign = ContentAlignment.MiddleCenter;
        _hint.Size = new Size(480, 22);
        _hint.Location = new Point(0, 34);
        mask.Controls.Add(_hint);

        var barTrack = new Panel();
        barTrack.Size = new Size(480, 4);
        barTrack.Location = new Point(0, 68);
        barTrack.BackColor = track;
        mask.Controls.Add(barTrack);
        _barFill = new Panel();
        _barFill.Size = new Size(96, 4);
        _barFill.Location = new Point(0, 0);
        _barFill.BackColor = fill;
        barTrack.Controls.Add(_barFill);

        splash.Show();
        splash.Refresh();
        Application.DoEvents();
        Stamp(root, "splash-shown");

        string art = Path.Combine(root, "assets", "skins", skinId, "splash.png");
        if (!File.Exists(art)) art = Path.Combine(root, "assets", "banner.png");
        if (File.Exists(art))
        {
            try
            {
                var pb = new PictureBox();
                pb.Image = Image.FromFile(art);
                pb.SizeMode = PictureBoxSizeMode.StretchImage;
                pb.Size = new Size(480, 320);
                pb.Location = Point.Empty;
                pb.BackColor = bg;
                splash.Controls.Add(pb);
                pb.SendToBack();
                splash.Refresh();
                Stamp(root, "splash-art");
            }
            catch { }
        }

        string runtime = Path.Combine(root, "data", "runtime");
        Directory.CreateDirectory(runtime);
        _cmdFile = Path.Combine(runtime, "launcher-splash.cmd");
        try { if (File.Exists(_cmdFile)) File.Delete(_cmdFile); } catch { }

        var psi = new ProcessStartInfo();
        psi.FileName = "powershell.exe";
        psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + meat + "\"";
        psi.WorkingDirectory = root;
        psi.WindowStyle = ProcessWindowStyle.Hidden;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        psi.EnvironmentVariables["DK_BOOT_SPLASH"] = "1";
        psi.EnvironmentVariables["DK_UI_MUTEX"] = mutexName;
        _meat = Process.Start(psi);
        Stamp(root, "meat-spawned pid=" + (_meat == null ? "?" : _meat.Id.ToString()));

        _startAt = DateTime.Now;
        _limitSec = firstBoot ? 600 : 180;

        var barTimer = new System.Windows.Forms.Timer();
        barTimer.Interval = 100;
        barTimer.Tick += delegate
        {
            _barPos += _barDir * 32;
            if (_barPos >= 384) { _barPos = 384; _barDir = -1; }
            if (_barPos <= 0) { _barPos = 0; _barDir = 1; }
            try { _barFill.Location = new Point(_barPos, 0); } catch { }
        };
        barTimer.Start();

        var watch = new System.Windows.Forms.Timer();
        watch.Interval = 40;
        watch.Tick += delegate { TickWatch(splash, root); };
        watch.Start();

        Application.Run(splash);
        try { barTimer.Stop(); } catch { }
    }

    static void TickWatch(Form splash, string root)
    {
        try
        {
            if (File.Exists(_cmdFile))
            {
                string raw = File.ReadAllText(_cmdFile);
                if (raw.StartsWith("ready", StringComparison.Ordinal))
                {
                    Stamp(root, "splash-ready");
                    splash.Close();
                    return;
                }
                if (raw.StartsWith("fail", StringComparison.Ordinal))
                {
                    string[] lines = raw.Replace("\r", "").Split('\n');
                    string msg = lines.Length > 1 ? lines[1].Trim() : "";
                    if (msg.Length == 0) msg = "界面没加载出来 · 关掉再开一次 Daemonkey.exe";
                    _hint.Text = msg;
                    if (_failAt == DateTime.MinValue) { _failAt = DateTime.Now; Stamp(root, "splash-fail"); }
                }
            }
            if (_failAt != DateTime.MinValue && (DateTime.Now - _failAt).TotalSeconds >= 20)
            {
                splash.Close();
                return;
            }
            if (_meat != null && _meat.HasExited && !File.Exists(_cmdFile))
            {
                _hint.Text = "启动中断 · 再双击一次 Daemonkey.exe";
                if (_failAt == DateTime.MinValue) { _failAt = DateTime.Now; Stamp(root, "meat-exited"); }
            }
            if ((DateTime.Now - _startAt).TotalSeconds >= _limitSec) splash.Close();
        }
        catch { }
    }

    static void ActivateExisting()
    {
        IntPtr h = FindWindow(null, "Daemonkey-splash");
        if (h == IntPtr.Zero) h = FindWindow(null, "Daemonkey");
        if (h != IntPtr.Zero)
        {
            ShowWindow(h, 9);
            SetForegroundWindow(h);
        }
    }

    static string ReadSkin(string root)
    {
        try
        {
            string p = Path.Combine(root, "data", "runtime", "launcher-skin.json");
            if (!File.Exists(p)) return "daimon";
            string j = File.ReadAllText(p);
            if (j.IndexOf("classic", StringComparison.OrdinalIgnoreCase) >= 0) return "classic";
        }
        catch { }
        return "daimon";
    }

    static string ShortHash(string s)
    {
        using (var sha = SHA256.Create())
        {
            byte[] b = sha.ComputeHash(Encoding.UTF8.GetBytes(s));
            var sb = new StringBuilder(16);
            for (int i = 0; i < 8; i++) sb.Append(b[i].ToString("X2"));
            return sb.ToString();
        }
    }

    static GraphicsPath RoundPath(int w, int h, int r)
    {
        int d = r * 2;
        var path = new GraphicsPath();
        path.AddArc(0, 0, d, d, 180, 90);
        path.AddArc(w - d - 1, 0, d, d, 270, 90);
        path.AddArc(w - d - 1, h - d - 1, d, d, 0, 90);
        path.AddArc(0, h - d - 1, d, d, 90, 90);
        path.CloseFigure();
        return path;
    }

    static void Stamp(string root, string msg)
    {
        try
        {
            string dir = Path.Combine(root, "data", "runtime");
            Directory.CreateDirectory(dir);
            File.AppendAllText(Path.Combine(dir, "launcher-boot.log"),
                DateTime.Now.ToString("HH:mm:ss.fff") + " " + msg + Environment.NewLine, Encoding.UTF8);
        }
        catch { }
    }
}
