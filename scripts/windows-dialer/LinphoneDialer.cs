// Linphone Dialer: click a phone number anywhere on Windows and Linphone dials it.
//
// Linphone 6.2 does register for tel: links, but a call it starts from a link (or from its
// command line) goes out with media encryption forced to none, whatever linphonerc says.
// A carrier that requires SRTP answers "488 Media Encryption Required", so the click looks
// like it did nothing. A call started from Linphone's own dialer uses the SRTP setting, so
// this app takes the link and presses the buttons for you, through UI Automation:
// Calls > New call > dialer > number > Call. Qt gives Windows the same accessible names it
// gives the Mac, so these are the same steps as the Mac app next door.
//
// Opened by hand, it takes over Linphone's own tel: and callto: links for this Windows user, so
// a link that would have opened Linphone opens this app instead. Settings won't offer a
// per-user app like this one as a default, but it does offer Linphone, so if Linphone isn't the
// default for those links yet, it opens Settings on Linphone's page.
// Build and install: build.ps1, next to this file.

using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Automation;
using System.Windows.Forms;
using Microsoft.Win32;

// Windows shows this name for the app instead of its file name.
[assembly: AssemblyTitle("Linphone Dialer")]
[assembly: AssemblyProduct("Linphone Dialer")]

static class LinphoneDialer
{
    static readonly string[] Schemes = { "tel", "callto" };

    [STAThread]
    static void Main(string[] args)
    {
        if (args.Length == 0) { SetUp(); return; }
        string number = NumberFrom(args[0]);
        if (number.Length == 0) return;
        string linphone = LinphonePath();
        if (linphone == null) { Failed(number, "Linphone isn't installed."); return; }
        // Started again while it runs, Linphone shows its window; otherwise it starts.
        Process.Start(linphone);
        if (!new LinphoneUI(Path.GetFileNameWithoutExtension(linphone)).Dial(number))
            Failed(number, "Linphone didn't show its dialer in time.");
    }

    // Decoded first: a link written tel:%2B1... would otherwise lose its + and dial a 2 in
    // front. A comma is a pause before an extension, so the number ends there.
    static string NumberFrom(string link)
    {
        string text = Uri.UnescapeDataString(link);
        text = text.Substring(text.IndexOf(':') + 1);
        int end = text.IndexOfAny(new[] { ';', '?', ',' });
        if (end >= 0) text = text.Substring(0, end);
        return new string(text.Where(c => (c >= '0' && c <= '9') || c == '+').ToArray());
    }

    static string LinphonePath()
    {
        // Linphone's installer registers this for all users, wherever it was installed. Read from
        // the machine's copy: this user's copy points here. The path is unquoted, spaces and all,
        // so it ends at .exe.
        using (var key = Registry.LocalMachine.OpenSubKey(@"Software\Classes\Linphone.tel\shell\open\command"))
        {
            string command = key == null ? null : key.GetValue("") as string;
            int end = command == null ? -1 : command.IndexOf(".exe", StringComparison.OrdinalIgnoreCase);
            if (end > 0)
            {
                string exe = command.Substring(0, end + 4).Trim().TrimStart('"');
                if (File.Exists(exe)) return exe;
            }
        }
        string usual = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
                                    @"Linphone\bin\linphone.exe");
        return File.Exists(usual) ? usual : null;
    }

    // Windows reads a user's own classes before the machine's, and remembers a default app by
    // its class name, so this user's Linphone.tel opens this app and stays the chosen default.
    // Removing the two keys under HKCU\Software\Classes undoes it.
    static void SetUp()
    {
        if (LinphonePath() == null)
        {
            Finish("Linphone Dialer", "Install Linphone first, then open Linphone Dialer again.");
            return;
        }
        string me = Application.ExecutablePath;
        foreach (string scheme in Schemes)
            using (var key = Registry.CurrentUser.CreateSubKey(@"Software\Classes\Linphone." + scheme + @"\shell\open\command"))
                key.SetValue("", "\"" + me + "\" \"%1\"");
        SHChangeNotify(0x08000000, 0, IntPtr.Zero, IntPtr.Zero);   // SHCNE_ASSOCCHANGED

        string[] elsewhere = Schemes.Where(s => DefaultFor(s) != "Linphone." + s).ToArray();
        if (elsewhere.Length == 0)
        {
            Finish("Linphone Dialer", "Phone links now dial in Linphone, encrypted.");
            return;
        }
        Process.Start("ms-settings:defaultapps?registeredAppMachine=Linphone");
        Finish("Linphone Dialer", "One more step: Settings is open on Linphone. Choose Linphone for "
            + string.Join(" and ", elsewhere.Select(s => s.ToUpperInvariant()))
            + ", and phone links dial in Linphone, encrypted.");
    }

    static string DefaultFor(string scheme)
    {
        // Newer Windows 11 builds keep the choice in UserChoiceLatest, older ones in UserChoice.
        string root = @"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\" + scheme;
        foreach (string path in new[] { root + @"\UserChoiceLatest\ProgId", root + @"\UserChoice" })
            using (var key = Registry.CurrentUser.OpenSubKey(path))
            {
                string chosen = key == null ? null : key.GetValue("ProgId") as string;
                if (!string.IsNullOrEmpty(chosen)) return chosen;
            }
        return null;
    }

    /// The number goes on the clipboard, so the call is one paste away.
    static void Failed(string number, string reason)
    {
        Clipboard.SetText(number);
        Finish("Couldn't dial " + number + " in Linphone", reason + "\n\nThe number is on your clipboard.");
    }

    static void Finish(string title, string text)
    {
        MessageBox.Show(text, title);
    }

    [DllImport("shell32.dll")]
    static extern void SHChangeNotify(int eventId, uint flags, IntPtr item1, IntPtr item2);
}

/// Linphone's window, read and pressed through UI Automation. Elements are found by their
/// accessible names, as Linphone 6.2 labels them.
class LinphoneUI
{
    readonly string processName;

    public LinphoneUI(string processName) { this.processName = processName; }

    public bool Dial(string number)
    {
        if (!Wait(() => Named("Open calls pages").Any(), 15)) return false;
        if (!Named("Close numeric pad").Any())
        {
            Press(Named("Open calls pages").FirstOrDefault());
            if (Wait(() => Named("Create new call").Any(), 2)) Press(Named("Create new call").FirstOrDefault());
            if (!Wait(() => Named("Search bar : Find contact").Any())) return false;
            // The panel's dialer button only shows while its field is empty. The first
            // "Open dialer" belongs to the top bar; the panel's own comes after it.
            foreach (var clear in Named("Clear text input")) Press(clear);
            if (!Wait(() => Named("Open dialer").Length >= 2)) return false;
            Press(Named("Open dialer").Last());
        }
        if (!Wait(() => Named("Close numeric pad").Any())) return false;
        var field = Named("Search bar : Find contact").FirstOrDefault();
        if (field == null) return false;
        ((ValuePattern)field.GetCurrentPattern(ValuePattern.Pattern)).SetValue(number);
        Thread.Sleep(400);
        // The keypad's Call button comes after the call history's own Call buttons.
        var call = Named("Call").LastOrDefault();
        if (call == null) return false;
        Press(call);
        return true;
    }

    AutomationElement[] Named(string name)
    {
        var match = new OrCondition(new PropertyCondition(AutomationElement.NameProperty, name),
                                    new PropertyCondition(AutomationElement.HelpTextProperty, name));
        try
        {
            return Process.GetProcessesByName(processName)
                .SelectMany(p => AutomationElement.RootElement.FindAll(TreeScope.Children,
                    new PropertyCondition(AutomationElement.ProcessIdProperty, p.Id)).Cast<AutomationElement>())
                .SelectMany(window => window.FindAll(TreeScope.Descendants, match).Cast<AutomationElement>())
                .ToArray();
        }
        catch (ElementNotAvailableException)
        {
            // Linphone swapped a page out mid-search. The caller is polling, so ask again.
            return new AutomationElement[0];
        }
    }

    static void Press(AutomationElement element)
    {
        if (element == null) return;
        ((InvokePattern)element.GetCurrentPattern(InvokePattern.Pattern)).Invoke();
        Thread.Sleep(300);
    }

    static bool Wait(Func<bool> ready, double seconds = 5)
    {
        var deadline = DateTime.Now.AddSeconds(seconds);
        while (!ready())
        {
            if (DateTime.Now > deadline) return false;
            Thread.Sleep(100);
        }
        return true;
    }
}
