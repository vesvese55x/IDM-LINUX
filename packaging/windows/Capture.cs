using System;
using System.Drawing;
using System.IO;
using System.Collections;
using System.Reflection;
using System.Threading;
using System.Windows.Forms;
using Semox;
class NativeCapture
{
    static BindingFlags flags=BindingFlags.Instance|BindingFlags.NonPublic|BindingFlags.Public;
    static int checks;
    static object Field(object value,string name){return value.GetType().GetField(name,flags).GetValue(value);}
    static void Check(bool ok,string why){checks++;if(!ok)throw new Exception(why);}
    static void Pump(int ms){DateTime until=DateTime.UtcNow.AddMilliseconds(ms);while(DateTime.UtcNow<until){Application.DoEvents();Thread.Sleep(10);}}
    static void Capture(Form form,string file){using(Bitmap b=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(b,new Rectangle(Point.Empty,form.Size));b.Save(file);}}
    static void BrowserTests()
    {
        using(Form host=new Form())
        {
            BrowsersPage page=new BrowsersPage(null);page.Dock=DockStyle.Fill;host.Controls.Add(page);host.Show();
            foreach(string language in new string[]{"tr","en","de","fr","ru","zh","ja","hi","ar","nl","fa","el","pt","vi","az","ky","it","id","ka","ro"})
            {
                I18n.SetLanguage(language);page.ApplyLang();
                foreach(int width in new int[]{450,650,1000,1600})
                {
                    host.ClientSize=new Size(width,900);page.Relayout();Pump(15);
                    foreach(string name in new string[]{"_bChrome","_bFirefox","_bResync","_bOpenDir","_bCopyDir"})
                    {
                        Control button=(Control)Field(page,name);Control card=button.Parent;
                        Check(button.Left>=0&&button.Right<=card.ClientSize.Width&&button.Top>=0&&button.Bottom<=card.ClientSize.Height,"button clipped: "+language+"/"+width+"/"+name);
                        foreach(Control other in card.Controls)
                            if(other!=button&&other.Visible&&other.Text.Length>0)Check(!button.Bounds.IntersectsWith(other.Bounds),"button covered: "+name+" by "+other.GetType().Name);
                        foreach(Point sample in new Point[]{new Point(2,2),new Point(button.Width/2,button.Height/2),new Point(button.Width-3,button.Height-3)})
                            Check(card.GetChildAtPoint(new Point(button.Left+sample.X,button.Top+sample.Y))==button,"button hit-test blocked: "+name);
                    }
                }
            }
            host.Close();
        }
    }
    [STAThread]static void Main(string[] args)
    {
        try
        {
            if(Environment.OSVersion.Platform!=PlatformID.Win32NT&&Environment.GetEnvironmentVariable("SEMO_ALLOW_MONO_TEST")!="1")throw new Exception("Screenshots require native Windows.");
            Application.EnableVisualStyles();Settings.Set("clipwatch","0");Settings.Set("warm","0");Settings.Set("lang","tr");Settings.Set("dldir",Path.Combine(Path.GetTempPath(),"IDM-SEMO-capture-downloads"));Settings.Save();
            BrowserTests();
            if(Environment.OSVersion.Platform!=PlatformID.Win32NT){Console.WriteLine("MONO_BROWSER_LAYOUT_PASS assertions="+checks+"; screenshots deliberately skipped");return;}
            I18n.SetLanguage("tr");
            string output=args[0];Directory.CreateDirectory(output);
            MainForm main=new MainForm();main.ClientSize=new Size(1440,960);main.Show();I18n.SetLanguage("tr");main.ApplyLang();Pump(300);
            string[] names={"installer","overview","browsers","settings","doctor","projects","support","language","about","torrent-ed2k"};
            for(int index=0;index<names.Length;index++){main.ShowPage(index);Pump(180);Capture(main,Path.Combine(output,names[index]+".png"));}
            main.Hide();Console.WriteLine("NATIVE_BROWSER_CAPTURE_PASS assertions="+checks+" platform="+Environment.OSVersion+" renderer=WinForms-DrawToBitmap");
        }
        catch(Exception error){Console.Error.WriteLine(error);Environment.Exit(1);}
    }
}
