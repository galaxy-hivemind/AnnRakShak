import { createFileRoute } from '@tanstack/react-router';
import { NeedsReview } from '@/features/annarakshak/review';
import { pageHead } from '@/features/annarakshak/meta';
import { scansQuery } from '@/services/api';
import { Loading, ErrorState } from '@/features/annarakshak/common';
export const Route = createFileRoute('/review')({loader:async({context})=>{await context.queryClient.ensureQueryData(scansQuery);},head:()=>pageHead('Needs Review','Check ambiguous, missing, conflicting, and incomplete date evidence before explicitly confirming products.'),pendingComponent:Loading,errorComponent:({error,reset})=><ErrorState error={error} retry={reset}/>,component:NeedsReview});
