import { createFileRoute } from '@tanstack/react-router';
import { Scan } from '@/features/annarakshak/scan';
import { pageHead } from '@/features/annarakshak/meta';
export const Route = createFileRoute('/scan')({head:()=>pageHead('Scan Product','Capture packaging. Check printed date evidence. Confirm details into your inventory.'),component:Scan});
