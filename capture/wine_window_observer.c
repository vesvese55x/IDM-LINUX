/* Read-only Win32 geometry observer. GUI subsystem: never opens a console. */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <wchar.h>
#include <stdint.h>
static FILE *f;static int comma;static HWND rootwin;
static void string(const wchar_t *s){char b[24000];WideCharToMultiByte(CP_UTF8,0,s,-1,b,sizeof(b),NULL,NULL);fputc('"',f);for(char*p=b;*p;p++){unsigned char c=*p;if(c=='"'||c=='\\'){fputc('\\',f);fputc(c,f);}else if(c<32)fprintf(f,"\\u%04x",c);else fputc(c,f);}fputc('"',f);}
static void item(HWND w){if(!IsWindowVisible(w))return;wchar_t title[4096]={0},cl[256]={0};RECT r;GetWindowTextW(w,title,4095);GetClassNameW(w,cl,255);if(!GetWindowRect(w,&r))return;if(comma++)fputc(',',f);fprintf(f,"{\"handle\":%llu,\"root\":%llu,\"visible\":true,\"enabled\":%s,\"text\":",(unsigned long long)(uintptr_t)w,(unsigned long long)(uintptr_t)rootwin,IsWindowEnabled(w)?"true":"false");string(title);fputs(",\"class\":",f);string(cl);fprintf(f,",\"rect\":[%ld,%ld,%ld,%ld]}",r.left,r.top,r.right-r.left,r.bottom-r.top);}
static BOOL CALLBACK child(HWND w,LPARAM p){item(w);return TRUE;}
static BOOL CALLBACK top(HWND w,LPARAM p){DWORD pid;GetWindowThreadProcessId(w,&pid);HANDLE proc=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,pid);if(!proc)return TRUE;wchar_t path[4096]={0};DWORD count=4096;BOOL ok=QueryFullProcessImageNameW(proc,0,path,&count);CloseHandle(proc);if(!ok)return TRUE;wchar_t*base=wcsrchr(path,L'\\');base=base?base+1:path;if(_wcsicmp(base,L'IDMan.exe')!=0)return TRUE;rootwin=w;item(w);EnumChildWindows(w,child,0);return TRUE;}
int WINAPI wWinMain(HINSTANCE a,HINSTANCE b,PWSTR cmd,int n){int argc;LPWSTR*argv=CommandLineToArgvW(GetCommandLineW(),&argc);if(argc<3)return 2;wchar_t temp[4096];_snwprintf(temp,4095,L"%ls.tmp",argv[1]);while(GetFileAttributesW(argv[2])==INVALID_FILE_ATTRIBUTES){f=_wfopen(temp,L"wb");if(f){comma=0;fprintf(f,"{\"foreground\":%llu,\"widgets\":[",(unsigned long long)(uintptr_t)GetForegroundWindow());EnumWindows(top,0);fputs("]}",f);fclose(f);MoveFileExW(temp,argv[1],MOVEFILE_REPLACE_EXISTING);}Sleep(300);}LocalFree(argv);return 0;}
