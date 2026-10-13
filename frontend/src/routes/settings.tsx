import { createFileRoute } from '@tanstack/react-router';
import { AppSettings } from '@/features/annarakshak/settings';
import { pageHead } from '@/features/annarakshak/meta';
import { settingsQuery } from '@/services/api';
import { Loading, ErrorState } from '@/features/annarakshak/common';
export const Route = createFileRoute('/settings')({loader:async({context})=>{await context.queryClient.ensureQueryData(settingsQuery);},head:()=>pageHead('Settings','Choose date attention and display preferences, and read the AnnaRakshak demo scanning and privacy notices.'),pendingComponent:Loading,errorComponent:({error,reset})=><ErrorState error={error} retry={reset}/>,component:AppSettings});
